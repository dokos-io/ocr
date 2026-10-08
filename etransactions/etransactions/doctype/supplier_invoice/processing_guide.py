# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

"""Where a Supplier Invoice stands and what to do next, in plain words.

The form used to show up to five status signals (the document status, the platform
pill, "Received via", the lifecycle ribbon and the supplier match confidence) and leave
the reading to the user. This module does the reading once, on the server:

- one status in task words (:data:`STATUSES`), stored in ``guide_status`` for the list;
- five steps: received, check, match the order, book, pay;
- checks that say why they matter and how to fix them;
- one next step with its main action, and the other options with their consequences.

It covers every Supplier Invoice. One received through an accredited platform also gets
what the supplier sees, from :mod:`~etransactions.plateforme_agreee.lifecycle_overview`.
Everything here only reads: actions are names the form turns into calls to existing
methods.
"""

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

import frappe
from frappe import _
from frappe.utils import flt, fmt_money, formatdate

if TYPE_CHECKING:
	from etransactions.etransactions.doctype.supplier_invoice.supplier_invoice import SupplierInvoice

# Guide status key -> (stored ``guide_status`` value, indicator colour).
STATUSES = {
	"file_missing": ("File Missing", "orange"),
	"to_review": ("To Review", "orange"),
	"to_match": ("To Match", "blue"),
	"ready": ("Ready to Book", "blue"),
	"booked": ("To Pay", "blue"),
	"paid": ("Paid", "green"),
	"completed": ("Completed", "green"),
	"disputed": ("Disputed", "orange"),
	"refused": ("Refused", "red"),
	"closed": ("Closed", "gray"),
}

# Platform decisions that put the invoice on hold until the supplier answers.
ON_HOLD = ("dispute", "suspended", "partially_approved")

# Check states, worst first. "error" stops booking, "todo" is the order link still to do.
CHECK_STATES = ("error", "todo", "warning", "ok")


@dataclass
class Check:
	key: str
	state: str  # see CHECK_STATES
	label: str
	detail: str | None = None
	action: dict | None = None
	fields: list[str] = field(default_factory=list)  # header fields the check is about
	rows: list[int] = field(default_factory=list)  # item rows (idx) the check is about

	def as_dict(self) -> dict:
		return asdict(self)


def action(key: str, label: str, **kwargs) -> dict:
	return {"action": key, "label": label, **kwargs}


class ProcessingGuide:
	def __init__(self, doc: "SupplierInvoice"):
		self.doc = doc
		self.settings = frappe.get_cached_doc("eTransactions Settings")
		self.order_required = not doc.is_return and not self.settings.no_purchase_order
		self.receipt_mode = bool(self.settings.reconcile_with_purchase_receipts)
		self.einvoice = self._get_einvoice()
		self.lifecycle = self._get_lifecycle_state()
		self.purchase_invoices = self._get_purchase_invoices()
		self._checks = None

	# --- Facts -----------------------------------------------------------------------

	@property
	def source(self) -> str:
		"""``platform``, ``einvoice`` (an e-invoice file outside a platform), ``ocr`` or ``manual``."""
		if self.einvoice:
			return "platform" if self.einvoice.pa_flow_id else "einvoice"
		return "ocr" if self.doc.ocr_request else "manual"

	@property
	def on_platform(self) -> bool:
		return self.source == "platform"

	@property
	def order_doctype(self) -> str:
		return "Purchase Receipt" if self.receipt_mode else "Purchase Order"

	@property
	def submitted_invoice(self):
		return next((pi for pi in self.purchase_invoices if pi.docstatus == 1), None)

	@property
	def draft_invoice(self):
		return next((pi for pi in self.purchase_invoices if pi.docstatus == 0), None)

	def _get_einvoice(self):
		if not self.doc.einvoice:
			return None
		return frappe.db.get_value(
			"eInvoice",
			self.doc.einvoice,
			["name", "einvoice_type", "pa_flow_id", "pa_content_state"],
			as_dict=True,
		)

	def _get_lifecycle_state(self) -> dict:
		if not self.einvoice or self.einvoice.einvoice_type != "Incoming":
			return {}
		from etransactions.etransactions.doctype.einvoice_event.einvoice_event import current_lifecycle_state

		return current_lifecycle_state(self.einvoice.name)

	def _get_purchase_invoices(self) -> list:
		if self.doc.is_new():
			return []
		return frappe.get_all(
			"Purchase Invoice",
			filters={"supplier_invoice": self.doc.name, "docstatus": ("<", 2)},
			fields=["name", "docstatus", "outstanding_amount", "due_date", "is_return"],
			order_by="docstatus desc, creation desc",
		)

	# --- Status ----------------------------------------------------------------------

	def status_key(self) -> str:
		state = self.lifecycle
		if self.doc.status == "Closed":
			return "closed"
		if state.get("refused") or state.get("cancelled"):
			return "refused"
		if (
			self.einvoice
			and self.einvoice.pa_flow_id
			and self.einvoice.pa_content_state in ("pending", "error")
		):
			return "file_missing"
		if invoice := self.submitted_invoice:
			if invoice.is_return:
				return "completed"
			paid = state.get("purchase") == "payment_sent" or flt(invoice.outstanding_amount) <= 0
			return "paid" if paid else "booked"
		if state.get("purchase") in ON_HOLD:
			return "disputed"

		worst = self.worst_check_state()
		if worst == "error":
			return "to_review"
		if worst == "todo":
			return "to_match"
		return "ready"

	def worst_check_state(self) -> str:
		states = {check.state for check in self.checks()}
		return next((s for s in CHECK_STATES if s in states), "ok")

	# --- Checks ----------------------------------------------------------------------

	def checks(self) -> list[Check]:
		if self._checks is None:
			self._checks = [
				check
				for check in (
					self._check_supplier(),
					*self._check_lines(),
					self._check_order_link() if not self.doc.is_return else self._check_credit_note(),
					self._check_totals(),
					self._check_duplicate(),
					self._check_order_reference(),
				)
				if check
			]
		return self._checks

	def _check_supplier(self) -> Check:
		doc = self.doc
		if not doc.supplier:
			read = doc.supplier_name or doc.tax_id
			fix = (
				action("create_supplier", _("Create the supplier"))
				if doc.tax_id
				else action("goto_field", _("Choose the supplier"), field="supplier")
			)
			return Check(
				"supplier",
				"error",
				_("Supplier not identified"),
				_("Read on the invoice: {0}").format(read)
				if read
				else _("No supplier name or tax ID could be read."),
				fix,
				fields=["supplier"],
			)

		how = {
			"ocr": _("matched from the data read on the PDF"),
			"manual": _("chosen on this invoice"),
		}.get(self.source, _("matched from the e-invoice"))
		if doc.match_confidence in ("medium", "low"):
			return Check(
				"supplier",
				"warning",
				_("Supplier guessed: check it"),
				_("{0}, {1}. The match is not certain.").format(doc.supplier_name or doc.supplier, how),
				action("goto_field", _("Check"), field="supplier"),
				fields=["supplier"],
			)
		return Check(
			"supplier",
			"ok",
			_("Supplier identified"),
			_("{0}, {1}").format(doc.supplier_name or doc.supplier, how),
			fields=["supplier"],
		)

	def _check_lines(self) -> list[Check]:
		doc = self.doc
		if doc.is_return and not doc.items:
			# A debit note gets its lines from the credit note allocation.
			return []
		if not doc.items:
			return [
				Check(
					"lines",
					"error",
					_("No invoice lines"),
					_("Add at least one line, or link an order to copy its lines."),
					action("goto_field", _("Add a line"), field="items"),
				)
			]

		checks = []
		missing = [item.idx for item in doc.items if not item.item_code]
		suggested = [item.idx for item in doc.items if item.item_code and item.item_match == "Suggested"]
		if missing:
			checks.append(
				Check(
					"items_missing",
					"error",
					_("{0} line(s) without an item").format(len(missing)),
					_("Line(s) {0}: choose the item to book them to.").format(", ".join(map(str, missing))),
					action("pick_item", _("Choose"), row=missing[0]),
					rows=missing,
				)
			)
		if suggested:
			checks.append(
				Check(
					"items_suggested",
					"warning",
					_("{0} line(s) with a suggested item").format(len(suggested)),
					_(
						"Line(s) {0} were matched by a guess on the description. Confirm or change them."
					).format(", ".join(map(str, suggested))),
					action("confirm_items", _("Confirm")),
					rows=suggested,
				)
			)
		if not missing:
			checks.append(
				Check(
					"items",
					"ok",
					_("All {0} line(s) have an item").format(len(doc.items)),
					self._match_summary(),
				)
			)
		return checks

	def _match_summary(self) -> str | None:
		labels = {
			"Learned": _("learned"),
			"Suggested": _("suggested"),
			"Confirmed": _("confirmed"),
			"Manual": _("chosen by hand"),
			"From Order": _("from the order"),
		}
		counts = {}
		for item in self.doc.items:
			if item.item_match:
				counts[item.item_match] = counts.get(item.item_match, 0) + 1
		return ", ".join(f"{count} {labels[key]}" for key, count in counts.items() if key in labels) or None

	def _check_order_link(self) -> Check | None:
		doc = self.doc
		if not self.order_required or not doc.items:
			return None

		unlinked = [
			item.idx for item in doc.items if not item.reference_doctype or not item.reference_docname
		]
		if unlinked:
			label = (
				_("{0} line(s) not linked to a purchase receipt")
				if self.receipt_mode
				else _("{0} line(s) not linked to a purchase order")
			)
			return Check(
				"order_link",
				"todo",
				label.format(len(unlinked)),
				_("Required by your purchase settings."),
				action(
					"select_orders", _("Link", context="Supplier Invoice action"), doctype=self.order_doctype
				),
				rows=unlinked,
			)

		drafts = sorted(
			{
				(item.reference_doctype, item.reference_docname)
				for item in doc.items
				if frappe.db.get_value(item.reference_doctype, item.reference_docname, "docstatus") != 1
			}
		)
		if drafts:
			doctype, name = drafts[0]
			return Check(
				"order_draft",
				"todo",
				_("{0} {1} is not submitted").format(_(doctype), name),
				_("Submit it before booking this invoice."),
				action("open_doc", _("Open"), doctype=doctype, name=name),
			)

		references = sorted({item.reference_docname for item in doc.items})
		return Check(
			"order_link",
			"ok",
			_("All lines linked to {0}").format(", ".join(references)),
			_("Submitted, so the order will show as billed."),
		)

	def _check_credit_note(self) -> Check | None:
		doc = self.doc
		if doc.items and not doc.credit_note_allocations:
			return None
		if doc.credit_note_allocations:
			return Check(
				"credit_note",
				"ok",
				_("Credit note allocated to {0} invoice(s)").format(len(doc.credit_note_allocations)),
			)
		return Check(
			"credit_note",
			"todo",
			_("Credit note not allocated"),
			_("Choose the invoices this credit note reduces."),
			action("allocate_credit_note", _("Allocate")),
		)

	def _check_totals(self) -> Check | None:
		doc = self.doc
		if not doc.items or not flt(doc.supplier_net_amount):
			return None

		precision = doc.precision("net_total")
		expected = abs(flt(doc.supplier_net_amount, precision))
		lines = abs(flt(doc.net_total, precision))
		if expected == lines:
			return Check(
				"totals",
				"ok",
				_("Totals match the supplier's figures"),
				_("{0} excl. VAT").format(fmt_money(expected, currency=doc.currency)),
				fields=["supplier_net_amount"],
			)
		return Check(
			"totals",
			"warning",
			_("Totals differ from the supplier's figures"),
			_("The lines add up to {0} excl. VAT, the invoice says {1}.").format(
				fmt_money(lines, currency=doc.currency), fmt_money(expected, currency=doc.currency)
			),
			action("goto_field", _("Check the lines"), field="items"),
			fields=["supplier_net_amount"],
		)

	def _check_duplicate(self) -> Check | None:
		doc = self.doc
		if not doc.bill_no or not doc.supplier:
			return None
		booked = [
			pi
			for pi in frappe.get_all(
				"Purchase Invoice",
				filters={"bill_no": doc.bill_no, "supplier": doc.supplier, "docstatus": 1},
				fields=["name", "supplier_invoice"],
				limit=5,
			)
			# The NULL-safe comparison is done here: "!=" in SQL drops the empty ones.
			if pi.supplier_invoice != doc.name
		]
		if booked:
			return Check(
				"duplicate",
				"error",
				_("Already booked in {0}").format(booked[0].name),
				_("A purchase invoice with the same supplier and number {0} is submitted.").format(
					doc.bill_no
				),
				action("open_doc", _("Open"), doctype="Purchase Invoice", name=booked[0].name),
				fields=["bill_no"],
			)
		return Check(
			"duplicate",
			"ok",
			_("Not booked yet"),
			_("No other purchase invoice {0} from this supplier.").format(doc.bill_no),
			fields=["bill_no"],
		)

	def _check_order_reference(self) -> Check | None:
		"""The order number printed on the invoice, when it does not lead to the order."""
		doc = self.doc
		if not doc.purchase_order_number or doc.is_return:
			return None
		order_supplier = frappe.db.get_value("Purchase Order", doc.purchase_order_number, "supplier")
		if not frappe.db.exists("Purchase Order", doc.purchase_order_number):
			return Check(
				"order_reference",
				"warning",
				_("Order {0} not found").format(doc.purchase_order_number),
				_("The invoice mentions this order number, but no purchase order has it."),
				fields=["purchase_order_number"],
			)
		if doc.supplier and order_supplier != doc.supplier:
			return Check(
				"order_reference",
				"warning",
				_("Order {0} is for another supplier").format(doc.purchase_order_number),
				_("The order was placed with {0}.").format(order_supplier),
				action("goto_field", _("Check"), field="supplier"),
				fields=["purchase_order_number", "supplier"],
			)
		return None

	# --- Steps -----------------------------------------------------------------------

	def steps(self, status: str) -> list[dict]:
		doc = self.doc
		worst = self.worst_check_state()
		closed = status in ("refused", "closed")

		first = {
			"platform": _("Received"),
			"einvoice": _("Received"),
			"ocr": _("Uploaded"),
		}.get(self.source, _("Created"))
		received = {"key": "received", "label": first, "state": "done", "note": formatdate(doc.creation)}
		if status == "file_missing":
			received.update(state="warning", note=_("File not downloaded"))

		check = {"key": "check", "label": _("Check"), "state": "done", "note": _("All good")}
		if worst == "error":
			errors = len([c for c in self.checks() if c.state == "error"])
			check.update(state="current", note=_("{0} to fix").format(errors))
		elif status == "disputed":
			check.update(state="warning", note=_("Disputed"))
		elif status == "file_missing":
			check.update(state="todo", note=None)

		match = {"key": "match", "label": _("Match order"), "state": "todo", "note": None}
		if doc.is_return:
			match.update(label=_("Allocate"))
		if not self.order_required and not doc.is_return:
			match.update(state="skipped", note=_("Not required"))
		elif worst == "todo" and check["state"] == "done":
			match.update(state="current", note=_("Required"))
		elif worst in ("ok", "warning") and status not in ("file_missing",):
			references = sorted({i.reference_docname for i in doc.items if i.reference_docname})
			match.update(state="done", note=", ".join(references[:2]) or None)

		book = {
			"key": "book",
			"label": _("Book", context="Supplier Invoice step"),
			"state": "todo",
			"note": None,
		}
		pay = {"key": "pay", "label": _("Pay"), "state": "todo", "note": None}
		if invoice := self.submitted_invoice:
			book.update(state="done", note=invoice.name)
			if doc.is_return:
				pay.update(state="skipped", note=_("Not applicable"))
			elif status == "paid":
				pay.update(state="done", note=_("Paid"))
			else:
				pay.update(
					state="current",
					note=_("Due {0}").format(formatdate(invoice.due_date)) if invoice.due_date else None,
				)
		elif status == "ready":
			book.update(
				state="current",
				note=_("Draft {0}").format(self.draft_invoice.name) if self.draft_invoice else _("Your move"),
			)
		elif status == "disputed":
			book.update(state="skipped", note=_("On hold"))
			if match["state"] in ("todo", "current"):
				match.update(state="skipped", note=_("On hold"))

		steps = [received, check, match, book, pay]
		if closed:
			for step in steps:
				if step["state"] in ("todo", "current"):
					step.update(state="skipped", note=_("Not applicable"))
		return steps

	# --- Next step -------------------------------------------------------------------

	def next_step(self, status: str, overview: dict | None) -> dict:
		doc = self.doc
		supplier = doc.supplier_name or doc.supplier or _("the supplier")
		match status:
			case "file_missing":
				can_retry = bool(overview and overview.get("can_retry_download"))
				return {
					"tone": "orange",
					"title": _("Waiting for the original file"),
					"why": _(
						"The platform announced this invoice, but its file could not be downloaded yet."
					),
					"primary": action("retry_download", _("Retry download")) if can_retry else None,
				}
			case "to_review":
				first = next(c for c in self.checks() if c.state == "error")
				return {
					"tone": "orange",
					"title": self._review_title(first),
					"why": first.detail,
					"primary": first.action,
				}
			case "to_match":
				return self._match_step()
			case "ready":
				return self._ready_step(supplier)
			case "completed":
				invoice = self.submitted_invoice
				return {
					"tone": "green",
					"title": _("Debit note {0} is booked").format(invoice.name),
					"why": _("Nothing left to do on this credit note."),
					"primary": action(
						"open_doc",
						_("Open {0}").format(invoice.name),
						doctype="Purchase Invoice",
						name=invoice.name,
					),
				}
			case "booked":
				invoice = self.submitted_invoice
				why = _("Purchase invoice {0} is submitted.").format(invoice.name)
				if self.on_platform and self.settings.get("auto_send_payment"):
					why += " " + _("When you record the payment, the supplier is told automatically.")
				return {
					"tone": "green",
					"title": _("Pay {0} by {1}").format(supplier, formatdate(invoice.due_date))
					if invoice.due_date
					else _("Pay {0}").format(supplier),
					"why": why,
					"primary": action("record_payment", _("Record payment"), name=invoice.name),
					"secondary": [
						action(
							"open_doc",
							_("Open {0}").format(invoice.name),
							doctype="Purchase Invoice",
							name=invoice.name,
						)
					],
				}
			case "paid":
				return {
					"tone": "green",
					"title": _("Paid: nothing left to do"),
					"why": _("The purchase invoice is booked and paid."),
					"primary": None,
				}
			case "disputed":
				reported = self._decision_label()
				return {
					"tone": "orange",
					"title": _("Waiting for {0} to answer").format(supplier),
					"why": _(
						"You reported this invoice as {0}. The supplier should send a corrected invoice or a credit note."
						" If they confirm this one instead, you can still book it."
					).format(reported),
					"primary": None,
				}
			case "refused":
				primary = action("close", _("Close")) if doc.status != "Closed" else None
				return {
					"tone": "red",
					"title": _("Refused: this invoice will not be paid"),
					"why": _(
						"Refusal is final. The supplier must send a new invoice if an amount is still due."
					),
					"primary": primary,
				}
			case _:
				return {
					"tone": "gray",
					"title": _("Closed"),
					"why": _(
						"This invoice left your list without being booked. Reopen it to work on it again."
					),
					"primary": action("reopen", _("Reopen")),
				}

	def _review_title(self, check: Check) -> str:
		return {
			"supplier": _("Tell Dokos who sent this invoice"),
			"lines": _("Add the invoice lines"),
			"items_missing": _("Choose the item for each line"),
			"duplicate": _("This invoice seems to be booked already"),
		}.get(check.key, check.label)

	def _match_step(self) -> dict:
		doc = self.doc
		check = next(c for c in self.checks() if c.state == "todo")
		if check.key == "credit_note":
			return {
				"tone": "blue",
				"title": _("Allocate the credit note"),
				"why": check.detail,
				"primary": check.action,
			}
		if check.key == "order_draft":
			return {"tone": "blue", "title": check.label, "why": check.detail, "primary": check.action}

		if self.receipt_mode:
			title = _("Link the lines to the goods you received")
			why = _(
				"Your settings require each invoice line to come from a purchase receipt."
				" You then pay only for what was delivered, and the receipt shows as billed."
			)
			choose = _("Choose a receipt…")
		else:
			title = _("Link the lines to the purchase order you placed")
			why = _(
				"Your settings require each invoice line to come from a purchase order."
				" You then pay only for what you ordered, and the order shows as billed."
			)
			choose = _("Choose an order…")

		secondary = [action("select_orders", choose, doctype=self.order_doctype)]
		primary = None
		if candidate := self._candidate_order():
			why += " " + _("Open {0} for {1}: {2}.").format(
				_(self.order_doctype).lower(), doc.supplier_name or doc.supplier, candidate["description"]
			)
			primary = action(
				"link_order",
				_("Link {0}").format(candidate["name"]),
				doctype=self.order_doctype,
				name=candidate["name"],
			)
		else:
			primary, secondary = secondary[0], []
		if not self.receipt_mode:
			secondary.append(action("create_purchase_order", _("No order? Create one from this invoice")))
		return {"tone": "blue", "title": title, "why": why, "primary": primary, "secondary": secondary}

	def _candidate_order(self) -> dict | None:
		"""The open order or receipt that most likely goes with this invoice."""
		doc = self.doc
		if not doc.supplier:
			return None
		try:
			names = list(doc.get_matched_receipts() if self.receipt_mode else doc.get_matched_orders())
		except Exception:
			return None
		names = [n if isinstance(n, str) else n.get("name") for n in names]
		if len(names) != 1:
			return None
		values = frappe.db.get_value(
			self.order_doctype,
			names[0],
			["name", "net_total", "currency", "posting_date" if self.receipt_mode else "transaction_date"],
			as_dict=True,
		)
		if not values:
			return None
		date = values.get("posting_date") or values.get("transaction_date")
		same = flt(values.net_total) == flt(doc.supplier_net_amount)
		description = _("{0} ({1} excl. VAT, {2})").format(
			values.name, fmt_money(values.net_total, currency=values.currency), formatdate(date)
		)
		if same:
			description += " " + _("with the same amount")
		return {"name": values.name, "description": description}

	def _ready_step(self, supplier: str) -> dict:
		doc = self.doc
		if draft := self.draft_invoice:
			return {
				"tone": "blue",
				"title": _("Finish purchase invoice {0}").format(draft.name),
				"why": _("A draft purchase invoice already exists for this invoice. Check and submit it."),
				"primary": action(
					"open_doc", _("Open {0}").format(draft.name), doctype="Purchase Invoice", name=draft.name
				),
			}

		if doc.is_return:
			return {
				"tone": "blue",
				"title": _("Book the debit note"),
				"why": _("Creating the debit note books it and reconciles it with the allocated invoices."),
				"primary": action("create_purchase_invoice", _("Create debit note"), submit=1),
			}

		why = _("Everything checks out. Creating the purchase invoice books it in your accounts.")
		references = sorted({i.reference_docname for i in doc.items if i.reference_docname})
		if references:
			why += " " + _("{0} will show as billed.").format(", ".join(references))
		note = None
		if self.on_platform and self.settings.get("auto_send_approved"):
			note = _("This also tells {0} that the invoice is approved.").format(supplier)
		warnings = [c for c in self.checks() if c.state == "warning"]
		if warnings:
			why += " " + _("Have a look at the warnings below first.")
		return {
			"tone": "blue",
			"title": _("Book this invoice"),
			"why": why,
			"note": note,
			"primary": action("create_purchase_invoice", _("Create and submit purchase invoice"), submit=1),
			"secondary": [action("create_purchase_invoice", _("Create as draft"), submit=0)],
		}

	def _decision_label(self) -> str:
		from etransactions.plateforme_agreee import lifecycle_status

		return (
			lifecycle_status.label(self.lifecycle.get("purchase")) if self.lifecycle.get("purchase") else ""
		)

	# --- Options ---------------------------------------------------------------------

	def options(self, status: str, overview: dict | None) -> list[dict]:
		if status == "closed":
			return []

		options = []
		reportable = {a["status"]: a for a in (overview or {}).get("actions") or []}
		descriptions = {
			"dispute": (
				_(
					"Something is wrong: price, quantity, missing goods. The supplier should send a correction."
					" You can still approve or refuse later."
				),
				_("Notifies the supplier"),
			),
			"refused": (
				_(
					"You will never pay this invoice. The supplier must send a new one if anything is still due."
				),
				_("Final · notifies the supplier"),
			),
			"approved": (
				_("Tell the supplier now that the invoice is accepted, and book it later."),
				_("Notifies the supplier"),
			),
		}
		if self.on_platform and status not in ("refused", "paid", "completed"):
			order = (
				["approved", "dispute", "refused"]
				if status == "disputed"
				else ["dispute", "refused", "approved"]
			)
			for key in order + [k for k in reportable if k not in order and k != "payment_sent"]:
				definition = reportable.get(key)
				if not definition:
					continue
				if key == "approved" and status == "booked":
					continue
				description, tag = descriptions.get(key, (None, _("Notifies the supplier")))
				label = (
					_("Approve without booking")
					if key == "approved" and status != "disputed"
					else definition["label"]
				)
				options.append(
					{
						"key": key,
						"label": label,
						"description": description,
						"tag": tag,
						"tone": "red" if key == "refused" else None,
						"action": action("report_status", label, status=key),
					}
				)
		elif not self.on_platform and status not in ("booked", "paid", "completed", "refused"):
			options.append(
				{
					"key": "platform_unavailable",
					"label": _("Dispute or refuse"),
					"description": _(
						"Only for invoices received through an accredited platform. For this one, contact the supplier directly."
					),
					"tag": _("Not available"),
					"disabled": True,
				}
			)

		if status in ("paid", "completed"):
			return options
		if status in ("booked",):
			description = _("Use when the payment was made outside Dokos.")
			label = _("Close")
		elif status == "refused":
			return options
		else:
			label = _("Close without booking")
			description = (
				_("Not for you, or a duplicate. It leaves your list. The supplier is not told.")
				if self.on_platform
				else _(
					"You will not book this invoice: wrong recipient, duplicate or refused. It leaves your list. Tell the supplier yourself."
				)
			)
		options.append(
			{
				"key": "close",
				"label": label,
				"description": description,
				"tag": _("Internal only"),
				"action": action("close", label),
			}
		)
		return options

	# --- Output ----------------------------------------------------------------------

	def platform_line(self, overview: dict | None) -> str:
		if self.on_platform and overview:
			return overview.get("pill") or ""
		return {
			"einvoice": _("Imported e-invoice: nothing done here is sent to the supplier."),
			"ocr": _("Uploaded and read by OCR: nothing done here is sent to the supplier."),
		}.get(self.source, _("Entered by hand: nothing done here is sent to the supplier."))

	def as_dict(self) -> dict:
		overview = self._get_overview()
		key = self.status_key()
		label, tone = STATUSES[key]
		checks = self.checks()
		return {
			"source": self.source,
			"status": {"key": key, "label": _(label), "tone": tone},
			"platform": overview,
			"platform_line": self.platform_line(overview),
			"steps": self.steps(key),
			"next_step": self.next_step(key, overview),
			"checks": [c.as_dict() for c in checks],
			"open_checks": len([c for c in checks if c.state != "ok"]),
			"options": self.options(key, overview),
			"order_required": self.order_required,
			"order_doctype": self.order_doctype,
		}

	def _get_overview(self) -> dict | None:
		if not self.on_platform:
			return None
		from etransactions.plateforme_agreee.lifecycle_overview import get_overview

		try:
			return get_overview(self.einvoice.name)
		except Exception:
			# The guide still works without what the supplier sees.
			frappe.log_error(
				title="Supplier Invoice guide: platform overview failed",
				reference_doctype="eInvoice",
				reference_name=self.einvoice.name,
			)
			return None


def get_guide_status(doc: "SupplierInvoice") -> str:
	"""The stored ``guide_status`` value for a Supplier Invoice."""
	return STATUSES[ProcessingGuide(doc).status_key()][0]


def update_guide_status(name: str) -> None:
	"""Recompute and store ``guide_status`` after something outside the form changed it."""
	if not frappe.db.exists("Supplier Invoice", name):
		return
	doc = frappe.get_doc("Supplier Invoice", name)
	value = get_guide_status(doc)
	if doc.guide_status != value:
		doc.db_set("guide_status", value, update_modified=False, notify=True)
