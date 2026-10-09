# Copyright (c) 2024, Dokos SAS and contributors
# For license information, please see license.txt

import difflib
import json
import re
import time
from collections import defaultdict
from typing import TYPE_CHECKING

import frappe
from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
from erpnext.accounts.party import get_address_tax_category, get_due_date, set_taxes
from erpnext.accounts.services.payment_schedule import PaymentScheduleService
from erpnext.accounts.services.taxes import TaxService
from erpnext.controllers.accounts_controller import merge_taxes
from frappe import _
from frappe.contacts.doctype.address.address import get_default_address
from frappe.model.document import Document
from frappe.model.mapper import get_mapped_doc
from frappe.model.meta import child_table_fields, data_fieldtypes, default_fields
from frappe.model.workflow import apply_workflow, get_transitions, get_workflow, has_approval_access
from frappe.query_builder import Order
from frappe.utils import cint, flt, fmt_money, getdate, nowdate, sbool
from pypika.terms import ExistsCriterion

from etransactions.controllers.entity_resolver import (
	MIN_COMPANY_ALIAS_LENGTH,
	InvoiceEntityResolverMixin,
	company_name_key,
	is_learnable_vendor_name,
	normalize_vendor_name,
	resolve_buyer_company,
	resolve_ocr_buyer_company,
)
from etransactions.etransactions.doctype.etransactions_supplier_item_alias.etransactions_supplier_item_alias import (
	get_supplier_item_alias,
	normalize_supplier_item_code,
)
from etransactions.etransactions.doctype.supplier_invoice.processing_guide import (
	ProcessingGuide,
	get_guide_status,
	update_guide_status,
)

if TYPE_CHECKING:
	from erpnext.accounts.doctype.purchase_invoice.purchase_invoice import PurchaseInvoice
	from erpnext.accounts.doctype.purchase_invoice_item.purchase_invoice_item import PurchaseInvoiceItem
	from erpnext.buying.doctype.purchase_order.purchase_order import PurchaseOrder

	from etransactions.etransactions.doctype.etransactions_settings.etransactions_settings import (
		eTransactionsSettings,
	)
	from etransactions.etransactions.doctype.etransactions_supplier_name_alias.etransactions_supplier_name_alias import (
		eTransactionsSupplierNameAlias,
	)

ItemDetailsCtx = frappe._dict
ItemDetails = frappe._dict


EXCLUDED_FIELDS = [*default_fields, *child_table_fields, "status"]

REFERENCE_FIELDS = {
	"Purchase Order": {"reference_docname": "purchase_order", "row": "po_detail"},
	"Purchase Receipt": {"reference_docname": "purchase_receipt", "row": "pr_detail"},
}


class SupplierInvoice(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		from etransactions.etransactions.doctype.supplier_invoice_credit_note_allocation.supplier_invoice_credit_note_allocation import (
			SupplierInvoiceCreditNoteAllocation,
		)
		from etransactions.etransactions.doctype.supplier_invoice_item.supplier_invoice_item import (
			SupplierInvoiceItem,
		)

		bill_date: DF.Date | None
		bill_no: DF.Data | None
		company: DF.Link
		credit_note_allocations: DF.Table[SupplierInvoiceCreditNoteAllocation]
		currency: DF.Link
		due_date: DF.Date | None
		einvoice: DF.Link | None
		file: DF.Link | None
		file_url: DF.SmallText | None
		grand_total: DF.Currency
		guide_status: DF.Literal[
			"",
			"File Missing",
			"To Review",
			"To Match",
			"Ready to Book",
			"To Pay",
			"Paid",
			"Completed",
			"Disputed",
			"Refused",
			"Closed",
		]
		is_return: DF.Check
		items: DF.Table[SupplierInvoiceItem]
		match_confidence: DF.Literal["", "high", "medium", "low"] | None
		name: DF.Int | None
		net_total: DF.Currency
		ocr_basket: DF.Link | None
		ocr_request: DF.Link | None
		posting_date: DF.Date
		purchase_order_number: DF.Data | None
		status: DF.Literal["Pending", "In Progress", "Ready", "Completed", "Closed"]
		supplier: DF.Link
		supplier_grand_total: DF.Currency
		supplier_name: DF.Data | None
		supplier_net_amount: DF.Currency
		supplier_tax_amount: DF.Currency
		tax_category: DF.Link | None
		tax_id: DF.Data | None
		tax_total: DF.Currency
		taxes_and_charges: DF.Link | None
		title: DF.Data | None
		vendor_address: DF.SmallText | None
		vendor_iban: DF.Data | None
	# end: auto-generated types

	def validate(self):
		self._detect_manual_supplier_change()
		self._detect_manual_company_change()
		self.get_supplier()
		self.set_company_from_analysis()
		self.set_tax_category()
		self.set_tax_template()
		self.set_missing_values_in_items()
		self.set_item_match()

		if self.supplier:
			self.title = (
				f"{self.supplier_name or self.supplier} : {self.bill_no}"[:140]
				if self.bill_no
				else f"{self.supplier or self.supplier}"[:140]
			)
		else:
			self.title = _("Missing Supplier")
		self.calculate_due_date()

		if self.should_suggest_items():
			self.append_matched_receipts()

		if self.should_suggest_items():
			self.append_matched_orders()

		if self.should_suggest_items():
			self.prefill_items()

		self.validate_credit_note_allocations()

	def should_suggest_items(self) -> bool:
		"""Suggest item lines on capture, or when the supplier or company changes.

		Not on every save with an empty table: that put back the lines a user had just deleted.
		"""
		if self.is_return or self.items:
			return False
		return self.is_new() or self.has_value_changed("supplier") or self.has_value_changed("company")

	def before_save(self):
		self.calculate_totals()

	def on_update(self):
		self.auto_reconcile()
		self._learn_supplier_item_aliases()
		if getattr(self, "_supplier_manually_set", False):
			self._learn_from_manual_match()
			self._maybe_update_supplier_tax_id()
		if getattr(self, "_company_manually_set", False):
			self._learn_company_alias()
		self.update_guide_status()

	def update_guide_status(self):
		value = get_guide_status(self)
		if self.guide_status != value:
			self.db_set("guide_status", value, update_modified=False)

	@frappe.whitelist()
	def get_processing_guide(self):
		"""What the Review tab shows: status, steps, checks, next step and options."""
		return ProcessingGuide(self).as_dict()

	def set_item_match(self):
		"""Record how each line got its item, so the form can say which ones to check.

		The intake paths set it when they fill a line. Here only a user's change is
		detected: an item chosen or replaced by hand is "Manual", a cleared one is reset.
		"""
		previous = {}
		if not self.is_new():
			previous = dict(
				frappe.get_all(
					"Supplier Invoice Item",
					filters={"parent": self.name, "parenttype": self.doctype},
					fields=["name", "item_code"],
					as_list=True,
				)
			)
		for item in self.items:
			if not item.item_code:
				item.item_match = None
			elif item.name in previous and previous[item.name] != item.item_code:
				item.item_match = "Manual"
			elif not item.item_match:
				item.item_match = "From Order" if item.reference_doctype else "Manual"

	@frappe.whitelist()
	def link_purchase_document(self, doctype: str, name: str) -> dict:
		"""Link the invoice lines to the lines of one order or receipt.

		A line is linked to the first open line of the order with the same item. An invoice
		with no lines yet takes the order's open lines instead, as the matching on save does.
		"""
		if doctype not in REFERENCE_FIELDS:
			frappe.throw(_("Only purchase orders and purchase receipts can be linked."))
		self.check_permission("write")
		order = frappe.get_doc(doctype, name)
		order.check_permission("read")
		if order.docstatus == 2:
			frappe.throw(_("{0} {1} is cancelled.").format(_(doctype), name))
		if self.supplier and order.supplier != self.supplier:
			frappe.throw(_("{0} {1} was placed with another supplier.").format(_(doctype), name))

		open_lines = [line for line in order.items if flt(line.billed_amt) < flt(line.net_amount)]
		taken = {item.row for item in self.items if item.reference_doctype == doctype and item.row}
		open_lines = [line for line in open_lines if line.name not in taken]

		linked = 0
		if not self.items:
			for line in open_lines:
				self.append(
					"items",
					{
						"item_code": line.item_code,
						"item_match": "From Order",
						"description": line.description,
						"qty": line.qty,
						"rate": line.rate,
						"amount": line.amount,
						"expense_account": line.expense_account,
						"cost_center": line.cost_center,
						"project": line.project,
						"item_tax_template": line.item_tax_template,
						"reference_doctype": doctype,
						"reference_docname": name,
						"row": line.name,
					},
				)
				linked += 1
		else:
			for item in self.items:
				if item.reference_docname:
					continue
				line = next(
					(line for line in open_lines if line.item_code and line.item_code == item.item_code), None
				)
				if not line:
					continue
				open_lines.remove(line)
				item.update({"reference_doctype": doctype, "reference_docname": name, "row": line.name})
				linked += 1

		self.supplier = self.supplier or order.supplier
		self.save()
		unlinked = [item.idx for item in self.items if not item.reference_docname]
		return {"linked": linked, "unlinked": unlinked}

	def _detect_manual_supplier_change(self):
		"""Flag a supplier the *user* chose, so the match can be learned and trusted.

		Only a human correction earns "high" confidence. `retry_supplier_match` sets
		`flags.automatic_supplier_match` before saving, because a bulk re-match is another
		guess: recording it as confirmed is what turned single-machine guesses into
		permanent aliases.
		"""
		if self.is_new() or self.flags.automatic_supplier_match:
			return
		db_supplier = frappe.db.get_value("Supplier Invoice", self.name, "supplier")
		if db_supplier != self.supplier and self.supplier:
			self._supplier_manually_set = True
			self.match_confidence = "high"

	def _detect_manual_company_change(self):
		"""Flag a company the user chose, so the receiver name can be learned."""
		if self.is_new() or not self.company:
			return
		if frappe.db.get_value("Supplier Invoice", self.name, "company") != self.company:
			self._company_manually_set = True

	def set_company_from_analysis(self):
		"""Match the buyer again while the company is empty: aliases and addresses may be new."""
		if self.company or not self.ocr_request:
			return
		if company := resolve_ocr_buyer_company(self._ocr_analysis()):
			self.company = company

	def _learn_company_alias(self):
		"""Remember the receiver name the user just mapped to a company.

		Like supplier aliases, a row is trusted as is on every later intake, so a name that
		already resolves, or that is a supplier's own name, is not stored.
		"""
		receiver_name = normalize_vendor_name(self._ocr_analysis().get("RECEIVER_NAME"))
		key = company_name_key(receiver_name)
		if len(key) < MIN_COMPANY_ALIAS_LENGTH:
			return
		if resolve_buyer_company(receiver_name, use_default=False) == self.company:
			return
		if frappe.db.exists("Supplier", {"supplier_name": receiver_name}):
			return

		claimants = {
			alias.company
			for alias in frappe.get_all("eTransactions Company Name Alias", fields=["receiver_name", "company"])
			if company_name_key(alias.receiver_name) == key
		}
		if claimants:
			if self.company not in claimants:
				frappe.log_error(
					f"Receiver name {receiver_name!r} is already mapped to {sorted(claimants)}; "
					f"not adding {self.company}.",
					_("Ambiguous receiver name alias"),
				)
			return

		alias = frappe.new_doc("eTransactions Company Name Alias")
		alias.company = self.company
		alias.receiver_name = receiver_name
		alias.insert(ignore_permissions=True)

	def _ocr_analysis(self) -> dict:
		if not self.ocr_request:
			return {}
		return frappe.parse_json(frappe.db.get_value("OCR Request", self.ocr_request, "analysis")) or {}

	def _learn_from_manual_match(self):
		"""Remember the vendor name the user just mapped, when it identifies that vendor.

		The alias table is consulted at "high" confidence on every later intake, so a bad
		row is not a missed match — it actively misroutes invoices. Anything that is not
		unambiguously this supplier's name is therefore dropped rather than stored.
		"""
		if not self.ocr_request:
			return
		raw_data = frappe.db.get_value("OCR Request", self.ocr_request, "analysis")
		if not raw_data:
			return

		vendor_name = normalize_vendor_name((frappe.parse_json(raw_data) or {}).get("VENDOR_NAME"))
		if not vendor_name or vendor_name == normalize_vendor_name(self.supplier_name):
			return

		# Our own letterhead read as the vendor block, or a fragment too generic to identify
		# anyone. Both are the OCR's error, not a mapping worth keeping.
		if not is_learnable_vendor_name(vendor_name):
			return

		claimants = set(
			frappe.get_all(
				"eTransactions Supplier Name Alias",
				filters={"vendor_name": vendor_name},
				pluck="supplier",
			)
		)
		if claimants:
			# Already known — either for this supplier (nothing to do) or for another one,
			# in which case a second row would make the name ambiguous and useless to both.
			if self.supplier not in claimants:
				frappe.log_error(
					f"Vendor name {vendor_name!r} is already mapped to {sorted(claimants)}; "
					f"not adding {self.supplier}.",
					_("Ambiguous supplier name alias"),
				)
			return

		alias: eTransactionsSupplierNameAlias = frappe.new_doc("eTransactions Supplier Name Alias")
		alias.supplier = self.supplier
		alias.vendor_name = vendor_name
		alias.insert(ignore_permissions=True)

	def _maybe_update_supplier_tax_id(self):
		if not self.supplier or not self.tax_id:
			return
		existing_tax_id = frappe.db.get_value("Supplier", self.supplier, "tax_id")
		if existing_tax_id:
			return

		normalized = re.sub(r"[\s\-\.]", "", self.tax_id).upper()
		if not normalized:
			return

		# Never propagate a buyer's own VAT onto a supplier master.
		company_tax_ids = {
			re.sub(r"[\s\-\.]", "", t).upper()
			for t in frappe.get_all("Company", filters={"tax_id": ("is", "set")}, pluck="tax_id")
			if t
		}
		if normalized in company_tax_ids:
			return

		# Don't write a tax_id already held by another supplier — that ambiguity is exactly
		# what breaks tax_id-based matching.
		for other_tax_id in frappe.get_all(
			"Supplier",
			filters={"name": ("!=", self.supplier), "tax_id": ("is", "set")},
			pluck="tax_id",
		):
			if re.sub(r"[\s\-\.]", "", other_tax_id).upper() == normalized:
				return

		frappe.db.set_value("Supplier", self.supplier, "tax_id", normalized)

	def get_supplier(self):
		if self.supplier:
			return

		ocr_data = self.get_ocr_analysis()

		# 1. The shared resolver — tax id, IBAN, confirmed alias, name. It is what the OCR and
		# e-invoicing intake paths already use; running a weaker matcher here made a later save
		# disagree with the intake about the same document.
		resolver = InvoiceEntityResolverMixin()
		if supplier := resolver.resolve_supplier(
			seller_name=ocr_data.get("VENDOR_NAME") or self.supplier_name,
			tax_id=self.tax_id,
			iban=self.vendor_iban,
		):
			self.supplier = supplier
			self.match_confidence = resolver._match_confidence
			return

		# 2. Previous invoices with same vendor address (improved: 20-char prefix + similarity ≥ 0.75)
		if self.vendor_address:
			invoices = frappe.get_all(
				"Supplier Invoice",
				filters={
					"vendor_address": ("like", f"{self.vendor_address[:20]}%"),
					"status": "Completed",
					"name": ("!=", self.name),
					"supplier": ("is", "set"),
				},
				fields=["supplier", "vendor_address"],
			)
			if invoices:
				best = max(
					invoices,
					key=lambda i: difflib.SequenceMatcher(
						None,
						(i.vendor_address or "").lower(),
						self.vendor_address.lower(),
					).ratio(),
				)
				if (
					difflib.SequenceMatcher(
						None,
						(best.vendor_address or "").lower(),
						self.vendor_address.lower(),
					).ratio()
					>= 0.75
				):
					self.supplier = best.get("supplier")
					self.match_confidence = "medium"
					return

		# 3. Previous OCR requests sharing the same VENDOR_URL
		if self.ocr_request:
			if ocr_data.get("VENDOR_URL"):
				if matching_ocr_requests := frappe.get_all(
					"OCR Request",
					filters={
						"analysis": ("like", f"%{ocr_data.get('VENDOR_URL')}%"),
						"name": ("!=", self.ocr_request),
					},
					limit=1,
					pluck="name",
				):
					matched_supplier = frappe.db.get_value(
						"Supplier Invoice", dict(ocr_request=matching_ocr_requests[0]), "supplier"
					)
					if matched_supplier:
						self.supplier = matched_supplier
						self.match_confidence = "medium"

	def calculate_due_date(self):
		if not self.due_date and self.supplier:
			try:
				self.due_date = get_due_date(
					posting_date=self.bill_date or self.posting_date or nowdate(),
					party_type="Supplier",
					party=self.supplier,
					company=self.company,
					bill_date=self.bill_date,
				)
			except Exception:
				pass

	def set_status(self, commit=False):
		status = "Pending"
		purchase_orders = frappe.get_all(
			"Purchase Order", dict(supplier_invoice=self.name, docstatus=("!=", 2)), pluck="docstatus"
		)
		if purchase_orders:
			status = "In Progress"
		if self.items and all(docstatus == 1 for docstatus in purchase_orders):
			status = "Ready"
		if frappe.db.exists("Purchase Invoice", dict(supplier_invoice=self.name, docstatus=("=", 1))):
			status = "Completed"

		self.status = status

		if commit:
			self.db_set("status", status, notify=True, commit=True)
			self.save_version()
			self.update_guide_status()

	@frappe.whitelist()
	def calculate_totals(self):
		self.net_total = 0.0
		self.tax_total = 0.0
		self.grand_total = 0.0
		try:
			if pi := frappe.db.exists("Purchase Invoice", dict(supplier_invoice=self.name)):
				doc: PurchaseInvoice = frappe.get_doc("Purchase Invoice", pi)  # type: ignore
			else:
				doc: PurchaseInvoice = frappe.new_doc("Purchase Invoice")  # type: ignore
				for item in self.items:
					doc.append("items", frappe.copy_doc(item).as_dict())
				doc.update(self.as_dict())
				for row in doc.items:
					if states_its_own_amount(row) or unit_price_exceeds_precision(row, row.precision("rate")):
						# One unit at the line's own amount survives qty * rate at any quantity,
						# and beats `set_missing_values` pricing a zero-rate row from purchase history.
						row.update({"qty": 1, "rate": flt(row.get("amount"))})
				doc.run_method("set_missing_values")
				# append taxes
				doc.set("taxes", [])
				if doc.taxes_and_charges:
					TaxService(doc).append_taxes_from_master()
				else:
					TaxService(doc).append_taxes_from_item_tax_template()

				doc.run_method("calculate_taxes_and_totals")

			self.net_total = doc.net_total or 0.0
			self.tax_total = doc.total_taxes_and_charges or 0.0
			self.grand_total = doc.grand_total or 0.0
		except Exception:
			frappe.clear_messages()
			self.log_error(_("Supplier Invoice totals could not be calculated"))

	def commit_totals(self):
		self.db_set("net_total", self.net_total)
		self.db_set("tax_total", self.tax_total)
		self.db_set("grand_total", self.grand_total)

	@frappe.whitelist()
	def get_document_item_lines(
		self, doctype, selected_documents, allow_child_item_selection, filtered_line_items
	):
		result = {"items": [], "supplier": None, "company": None}

		for selected_document in selected_documents:
			doc: PurchaseOrder | PurchaseInvoice = frappe.get_doc(doctype, selected_document)  # type: ignore

			if result["company"] and doc.company != result["company"]:
				frappe.throw(_("Please select documents linked to the same company"))

			if result["supplier"] and doc.supplier != result["supplier"]:
				frappe.throw(_("Please select documents linked to the same supplier"))

			result["supplier"] = doc.supplier
			result["company"] = doc.company

			if sbool(allow_child_item_selection):
				for item in doc.items:
					if item.name in filtered_line_items:
						result["items"].append(item)
			else:
				result["items"].extend(doc.items)

		return result

	def get_purchase_invoice(self, purchase_order_is_mandatory=True):
		from erpnext.buying.doctype.purchase_order.mapper import (
			make_purchase_invoice as make_purchase_invoice_from_po,
		)

		doc: PurchaseInvoice = frappe.new_doc("Purchase Invoice")  # type: ignore
		doc.ignore_pricing_rule = 1

		if purchase_order_is_mandatory:
			if self.items[0].reference_doctype == "Purchase Order":
				make_purchase_invoice_from_po(self.items[0].reference_docname, doc)
			elif self.items[0].reference_doctype == "Purchase Receipt":
				make_purchase_invoice_from_pr(self.items[0].reference_docname, doc)

		doc.set_posting_time = 1
		doc.posting_date = self.posting_date

		doc_items = doc.items

		def get_doc_item(item):
			name = REFERENCE_FIELDS.get(item.reference_doctype, {}).get("row")
			for doc_item in doc_items:
				if doc_item.get(name) == item.row:
					return frappe.copy_doc(doc_item).as_dict()
			else:
				try:
					source_item: PurchaseInvoiceItem = frappe.get_doc(
						f"{item.reference_doctype} Item", item.row
					)  # type: ignore
					source_item.parenttype = doc.doctype
					return frappe.copy_doc(source_item).as_dict()
				except Exception:
					return frappe._dict()

		doc.set("items", [])
		for item in self.items:
			ppi_row = frappe.copy_doc(item).as_dict()
			if self.is_return:
				# Credit notes have no return_against, so ERPNext does not enforce the
				# sign for us: force negative quantities so the invoice carries a credit
				# balance that can be reconciled against the allocated invoices.
				ppi_row["qty"] = -abs(flt(ppi_row.get("qty")))
				doc.append("items", ppi_row)
			else:
				doc_item = get_doc_item(item)
				new_row: dict = doc_item.update(ppi_row)  # type: ignore
				for key, value in REFERENCE_FIELDS.get(item.reference_doctype, {}).items():
					new_row[value] = item.get(key)

				row = doc.append("items", new_row)
				# Order and receipt lines keep their quantity: billing progress is counted on it.
				if not item.reference_doctype and unit_price_exceeds_precision(row, row.precision("rate")):
					row.update({"qty": 1, "rate": flt(row.get("amount"))})

		doc.is_return = bool(self.is_return)
		if doc.is_return:
			# The credit note keeps its own outstanding so it can be reconciled against
			# the allocated invoices via Payment Reconciliation.
			doc.update_outstanding_for_self = 1

		for field in frappe.get_meta(self.doctype).fields:
			if field.fieldname in EXCLUDED_FIELDS:
				continue
			if field.fieldtype in data_fieldtypes:
				doc.update({field.fieldname: self.get(field.fieldname)})

		# Explicitely remove discounts coming from POs
		doc.additional_discount_percentage = 0.0
		doc.discount_amount = 0.0

		doc.run_method("set_missing_values")
		doc.set("taxes", [])
		if doc.taxes_and_charges:
			TaxService(doc).append_taxes_from_master()
		else:
			TaxService(doc).append_taxes_from_item_tax_template()

		doc.run_method("calculate_taxes_and_totals")

		return doc

	def create_purchase_invoice(self, submit=False):
		if purchase_order_is_mandatory := not self.is_return and not frappe.db.get_single_value(
			"eTransactions Settings", "no_purchase_order"
		):
			for item in self.items:
				if not frappe.db.get_value(item.reference_doctype, item.reference_docname, "docstatus") == 1:
					frappe.throw(
						_("Please submit {0}: {1} before trying to create the corresponding invoice").format(
							_(item.reference_doctype), item.reference_docname
						)
					)

		doc: PurchaseInvoice = self.get_purchase_invoice(purchase_order_is_mandatory)
		doc.supplier_invoice = self.name  # type: ignore
		doc.insert(ignore_mandatory=True)

		if submit:
			if workflow_actions := self.get_workflow_actions("Purchase Invoice", doc):
				if len(workflow_actions) == 1:
					apply_workflow(doc, workflow_actions[0])
			else:
				doc.submit()

		if self.credit_note_allocations and doc.docstatus == 1:
			self.reconcile_credit_note_allocations(doc)

		return doc

	def create_purchase_order(self, transaction_date=None, submit=False):
		doc: PurchaseOrder = make_purchase_order(self.name)
		doc.transaction_date = transaction_date or nowdate()
		doc.insert()

		if submit:
			if workflow_actions := self.get_workflow_actions("Purchase Order", doc):
				if len(workflow_actions) == 1:
					apply_workflow(doc, workflow_actions[0])
			else:
				doc.submit()

		return doc

	def append_matched_orders(self):
		if frappe.db.get_single_value("eTransactions Settings", "reconcile_with_purchase_receipts"):
			return

		try:
			matched_orders = self.get_matched_orders()
			for matched_order in matched_orders:
				doc: PurchaseOrder = frappe.get_doc("Purchase Order", matched_order)  # type: ignore
				if doc.currency != self.currency:
					self.currency = doc.currency

				claimed_rows = self.get_rows_claimed_elsewhere(doc.doctype, doc.name)
				for item in doc.items:
					if item.billed_amt >= item.net_amount or item.name in claimed_rows:
						continue

					row = frappe.copy_doc(item).as_dict()
					row.pop("idx", None)
					row["reference_doctype"] = doc.doctype
					row["reference_docname"] = doc.name
					row["row"] = item.name
					row["item_match"] = "From Order"
					if row["qty"] == 1:
						rate = row["net_amount"] - row["billed_amt"]
						row["rate"] = min(rate, self.supplier_net_amount)

					row["amount"] = row["qty"] * row["rate"]
					self.append("items", row)
		except Exception:
			self.log_error()

	def get_rows_claimed_elsewhere(self, reference_doctype: str, reference_docname: str) -> set[str]:
		"""Rows of an order or receipt already on another supplier invoice that is not closed.

		Until that invoice is booked, the row is not billed yet, so `billed_amt` cannot tell
		that it is already taken.
		"""
		supplier_invoice = frappe.qb.DocType("Supplier Invoice")
		supplier_invoice_item = frappe.qb.DocType("Supplier Invoice Item")
		query = (
			frappe.qb.from_(supplier_invoice_item)
			.join(supplier_invoice)
			.on(supplier_invoice.name == supplier_invoice_item.parent)
			.select(supplier_invoice_item.row)
			.where(supplier_invoice_item.reference_doctype == reference_doctype)
			.where(supplier_invoice_item.reference_docname == reference_docname)
			.where(supplier_invoice.status != "Closed")
		)
		if self.name:
			query = query.where(supplier_invoice.name != self.name)

		return {row for row in query.run(pluck=True) if row}

	def get_matched_orders(self):
		purchase_order_dt = frappe.qb.DocType("Purchase Order")
		purchase_invoice_item_dt = frappe.qb.DocType("Purchase Invoice Item")

		subquery = (
			frappe.qb.from_(purchase_invoice_item_dt)
			.select(purchase_invoice_item_dt.name)
			.where(purchase_invoice_item_dt.docstatus.lt(2))
			.where(purchase_invoice_item_dt.purchase_order == purchase_order_dt.name)
		)

		query = (
			frappe.qb.from_(purchase_order_dt)
			.select(
				purchase_order_dt.name,
				purchase_order_dt.net_total,
				purchase_order_dt.order_confirmation_no,
				purchase_order_dt.company,
				purchase_order_dt.transaction_date,
			)
			.where(
				(purchase_order_dt.docstatus == 1)
				& (purchase_order_dt.per_billed.lt(100))
				& (purchase_order_dt.status.notin(["Closed", "Completed"]))
			)
			.where(ExistsCriterion(subquery).negate())
		)

		if self.supplier:
			query = query.where(purchase_order_dt.supplier == self.supplier)

		if self.company:
			query = query.where(purchase_order_dt.company == self.company)

		open_orders = query.run(as_dict=True)
		if (
			not getattr(self, "open_receipts", [])
			and len(open_orders) == 1
			and not frappe.db.get_single_value("eTransactions Settings", "no_single_purchase_order_match")
		):
			return open_orders

		matched_orders = set()
		if self.ocr_request:
			ocr_data = self.get_ocr_analysis()
			if ocr_data.get("PO_NUMBER"):
				for open_order in open_orders:
					if cites_reference(ocr_data["PO_NUMBER"], open_order.name):
						matched_orders.add(open_order.name)

			for child in ocr_data.get("items"):
				for open_order in open_orders:
					if cites_reference(
						child.get("expense_row"), open_order.name, open_order.order_confirmation_no
					):
						matched_orders.add(open_order.name)

		if not matched_orders:
			invoice_date = self.bill_date or self.posting_date
			for open_order in open_orders:
				# An order placed after the invoice cannot be the one it bills.
				if invoice_date and getdate(open_order.transaction_date) > getdate(invoice_date):
					continue
				if open_order.get("net_total") == self.supplier_net_amount:
					matched_orders.add(open_order.name)
					break

		return matched_orders

	def append_matched_receipts(self):
		if not self.purchase_order_number:
			return

		matched_receipts = self.get_matched_receipts()

		try:
			for matched_receipt in matched_receipts:
				doc = frappe.get_doc("Purchase Receipt", matched_receipt)
				if doc.currency != self.currency:
					self.currency = doc.currency

				claimed_rows = self.get_rows_claimed_elsewhere(doc.doctype, doc.name)
				for item in doc.items:
					if item.billed_amt >= item.net_amount or item.name in claimed_rows:
						continue

					row = frappe.copy_doc(item).as_dict()
					row.pop("idx", None)
					row["reference_doctype"] = doc.doctype
					row["reference_docname"] = doc.name
					row["row"] = item.name
					row["item_match"] = "From Order"

					if row["qty"] == 1:
						rate = row["net_amount"] - row["billed_amt"]
						row["rate"] = min(rate, self.supplier_net_amount)

					row["amount"] = row["qty"] * row["rate"]

					self.append("items", row)
		except Exception:
			self.log_error()

	def get_matched_receipts(self):
		purchase_receipt_dt = frappe.qb.DocType("Purchase Receipt")
		purchase_receipt_item_dt = frappe.qb.DocType("Purchase Receipt Item")
		purchase_order_dt = frappe.qb.DocType("Purchase Order")
		purchase_invoice_item_dt = frappe.qb.DocType("Purchase Invoice Item")

		subquery = (
			frappe.qb.from_(purchase_invoice_item_dt)
			.select(purchase_invoice_item_dt.name)
			.where(purchase_invoice_item_dt.docstatus.lt(2))
			.where(purchase_invoice_item_dt.purchase_order == purchase_receipt_dt.name)
		)

		query = (
			frappe.qb.from_(purchase_receipt_dt)
			.right_join(purchase_receipt_item_dt)
			.on(purchase_receipt_dt.name == purchase_receipt_item_dt.parent)
			.left_join(purchase_order_dt)
			.on(purchase_order_dt.name == purchase_receipt_item_dt.purchase_order)
			.select(
				purchase_receipt_dt.name,
				purchase_receipt_dt.net_total,
				purchase_receipt_dt.supplier_delivery_note,
				purchase_receipt_dt.company,
				purchase_order_dt.name.as_("purchase_order"),
				purchase_order_dt.order_confirmation_no,
			)
			.where(
				(purchase_receipt_dt.docstatus == 1)
				& (purchase_receipt_dt.per_billed.lt(100))
				& (purchase_receipt_dt.status.notin(["Closed", "Completed"]))
			)
			.where(ExistsCriterion(subquery).negate())
		)

		if self.supplier:
			query = query.where(purchase_receipt_dt.supplier == self.supplier)

		if self.company:
			query = query.where(purchase_receipt_dt.company == self.company)

		open_receipts = query.run(as_dict=True)
		self.open_receipts = open_receipts  # used to return order if single

		matched_orders = set()
		if self.ocr_request:
			ocr_data = self.get_ocr_analysis()
			if ocr_data.get("PO_NUMBER"):
				for open_order in open_receipts:
					if cites_reference(ocr_data["PO_NUMBER"], open_order.name, open_order.purchase_order):
						matched_orders.add(open_order.name)

			for child in ocr_data.get("items"):
				for open_order in open_receipts:
					if cites_reference(
						child.get("expense_row"),
						open_order.name,
						open_order.order_confirmation_no,
						open_order.supplier_delivery_note,
					):
						matched_orders.add(open_order.name)

		# Case 1: Perfect match between receipt and invoice
		if not matched_orders:
			for open_order in open_receipts:
				if self.purchase_order_number and (
					self.purchase_order_number != open_order.get("purchase_order")
				):
					continue

				if open_order.get("net_total") == flt(self.supplier_net_amount):
					matched_orders.add(open_order.name)
					break

		# Case 2: Perfect match between receipt and invoice
		if not matched_orders and flt(self.supplier_net_amount or 0.0) > 0:
			for open_order in open_receipts:
				if self.purchase_order_number and (
					self.purchase_order_number != open_order.get("purchase_order")
				):
					continue

				matched_orders.add(open_order.name)

		return matched_orders

	def get_ocr_analysis(self):
		if not self.ocr_request:
			return {}

		return frappe.get_doc("OCR Request", self.ocr_request).get_data_from_analysis()

	@frappe.whitelist()
	def close_request(self):
		self.db_set("status", "Closed", notify=True)
		self.save_version()
		self.run_method("on_close")
		self.update_guide_status()

	@frappe.whitelist()
	def open_request(self):
		self.status = "Pending"
		self.set_status(True)

	def set_tax_category(self):
		if not self.tax_category and self.supplier:
			tax_category = frappe.db.get_value("Supplier", self.supplier, "tax_category")
			party_address = get_default_address("Supplier", self.supplier)
			self.tax_category = get_address_tax_category(tax_category, party_address, party_address)

	def set_tax_template(self):
		if not self.taxes_and_charges:
			party_address = get_default_address("Supplier", self.supplier)  # Todo: avoid duplicate query
			self.taxes_and_charges = set_taxes(
				party=self.supplier,
				party_type="Supplier",
				posting_date=self.posting_date,
				company=self.company,
				customer_group=None,
				supplier_group=None,
				tax_category=self.tax_category,
				billing_address=party_address,
				shipping_address=party_address,
				use_for_shopping_cart=0,
			)

	def get_workflow_actions(self, doctype, doc):
		if frappe.db.get_value("Workflow", dict(document_type=doctype, is_active=True)):
			try:
				workflow = get_workflow(doctype)
				if hasattr(doc, "__islocal"):
					delattr(doc, "__islocal")
				doc.set(workflow.workflow_state_field, workflow.states[0].state)
				actions = [
					t.get("action")
					for t in get_transitions(doc, raise_exception=True)
					if has_approval_access(frappe.session.user, doc, t)
				]
				return actions
			except Exception:
				frappe.log_error(frappe.get_traceback(), "Workflow Error")
				return []

		return []

	def set_missing_values_in_items(self):
		for item in self.items:
			for field in ["project", "cost_center"]:
				if self.get(field) and not item.get(field):
					item.set(field, self.get(field))

	# --- Item line suggestions ----------------------------------------------

	def prefill_items(self):
		"""Suggest item lines for a captured invoice that has none.

		Neither intake path fills `items`: OCR only ever wrote the header, and the matched
		Purchase Order / Receipt route covers just the suppliers we order from. Everyone
		else's invoice arrives empty, so the same expense account and item get retyped every
		month for the same supplier.

		Two sources, in order of precision: the supplier item mapping, which recognises the
		individual lines; failing that, the supplier's last invoice, which at least gets the
		item and expense account right for the single-line suppliers that dominate this table.
		Everything suggested stays editable and nothing is submitted automatically.
		"""
		if not self.supplier or not self.company:
			return
		if not frappe.db.get_single_value("eTransactions Settings", "prefill_invoice_items"):
			return

		for row in self.get_mapped_captured_lines() or self.get_last_invoice_line():
			self.append("items", row)

	def get_mapped_captured_lines(self) -> list[dict]:
		"""Captured lines that the supplier item mapping recognises.

		Unrecognised lines are dropped rather than appended blank: raw OCR line text is
		mostly fragments ("Charges USD 3.39", "VAT USD 0.13"), and a row the user has to
		delete costs more than the one it saves.
		"""
		rows = []
		for line in self.get_ocr_analysis().get("items") or []:
			label = line.get("item") or line.get("expense_row")
			alias = get_supplier_item_alias(self.supplier, label)
			if not alias:
				continue

			rows.append(
				{
					"item_code": alias.item_code,
					"item_match": "Learned",
					"expense_account": alias.expense_account,
					"cost_center": alias.cost_center,
					"item_tax_template": alias.item_tax_template,
					"supplier_item_code": normalize_supplier_item_code(label),
					"supplier_description": label,
					"qty": flt(line.get("quantity")) or 1,
					"rate": flt(line.get("unit_price")) or flt(line.get("price")),
				}
			)

		return rows

	def get_last_invoice_line(self) -> list[dict]:
		"""A single line copying how this supplier's last invoice was booked."""
		if not flt(self.supplier_net_amount):
			# Without the amount OCR read, the line would only be a zero row to delete.
			return []

		last_invoice = frappe.get_all(
			"Purchase Invoice",
			filters={
				"supplier": self.supplier,
				"company": self.company,
				"docstatus": 1,
				"is_return": 0,
			},
			order_by="posting_date desc, creation desc",
			limit=1,
			pluck="name",
		)
		if not last_invoice:
			return []

		lines = frappe.get_all(
			"Purchase Invoice Item",
			filters={"parent": last_invoice[0], "parenttype": "Purchase Invoice"},
			fields=["item_code", "expense_account", "cost_center", "item_tax_template"],
			order_by="idx asc",
			limit=1,
		)
		if not lines:
			return []

		# The amount OCR read, not the previous invoice's: only the booking is being reused.
		return [{**lines[0], "item_match": "Suggested", "qty": 1, "rate": flt(self.supplier_net_amount)}]

	def _learn_supplier_item_aliases(self):
		"""Remember how the user mapped each captured line to an Item.

		Only rows that carry both the supplier's own label and a chosen Item teach anything;
		the alias controller refuses a label already mapped for this supplier, so a changed
		mapping has to be edited there rather than silently forked.
		"""
		if not self.supplier:
			# An unmatched invoice has nobody to attribute the mapping to.
			return

		for item in self.items:
			label = normalize_supplier_item_code(item.supplier_item_code or item.supplier_description)
			if not label or not item.item_code:
				continue
			if frappe.db.exists(
				"eTransactions Supplier Item Alias",
				{"supplier": self.supplier, "supplier_item_code": label},
			):
				continue

			alias = frappe.new_doc("eTransactions Supplier Item Alias")
			alias.supplier = self.supplier
			alias.supplier_item_code = label
			alias.item_code = item.item_code
			alias.expense_account = item.expense_account
			alias.cost_center = item.cost_center
			alias.item_tax_template = item.item_tax_template
			alias.insert(ignore_permissions=True)

	def validate_credit_note_allocations(self):
		"""Validate the multi-invoice credit note allocation table.

		The debit note is created independently of the invoices' outstanding, so any
		submitted supplier invoice can be a target (including already-paid ones). A
		single row may not be allocated more than that invoice's own amount, and the
		sum may not exceed the credit note amount.
		"""
		if not self.credit_note_allocations:
			return

		if not self.is_return:
			frappe.throw(_("Credit note allocations are only allowed when 'Is Debit Note' is checked."))

		precision = cint(frappe.db.get_default("currency_precision")) or 2
		total_allocated = 0.0
		for row in self.credit_note_allocations:
			if flt(row.allocated_amount) <= 0:
				continue

			total_allocated += flt(row.allocated_amount)

			pi = frappe.db.get_value(
				"Purchase Invoice", row.purchase_invoice, ["docstatus", "grand_total"], as_dict=True
			)
			# Drafts are allowed in the table but skipped at reconciliation time, so the
			# amount check only applies to submitted invoices.
			if not pi or pi.docstatus != 1:
				continue

			# The debit note is created independently of the invoice's outstanding, but a
			# single row may not be allocated more than the invoice's own amount.
			if flt(row.allocated_amount, precision) - flt(pi.grand_total, precision) > 0.009:
				frappe.throw(
					_("Row {0}: allocated amount {1} exceeds the invoice amount {2} of invoice {3}.").format(
						row.idx, row.allocated_amount, pi.grand_total, row.purchase_invoice
					)
				)

		self.calculate_totals()
		credit_amount = abs(flt(self.net_total, precision))
		if credit_amount and flt(total_allocated, precision) - credit_amount > 0.009:
			frappe.throw(
				_("Total allocated amount {0} exceeds the credit note amount {1}.").format(
					total_allocated, credit_amount
				)
			)

	@frappe.whitelist()
	def fetch_open_invoices_for_credit_note(self):
		"""Return submitted supplier invoices eligible for credit note allocation,
		oldest first (FIFO). Invoices are listed regardless of their outstanding — the
		debit note is created independently of it — and the invoice amount is returned
		for display in the dialog."""
		if not self.supplier:
			return []

		return frappe.get_all(
			"Purchase Invoice",
			filters={
				"supplier": self.supplier,
				"company": self.company,
				"docstatus": 1,
				"is_return": 0,
			},
			fields=["name", "bill_no", "posting_date", "grand_total as invoice_amount", "currency"],
			order_by="posting_date asc, name asc",
		)

	@frappe.whitelist()
	def allocate_credit_note_fifo(self):
		"""Compute a FIFO allocation of the credit note amount across open invoices.

		Returns the proposed rows (oldest invoice first) without mutating the
		document; the front-end populates the grid so amounts stay editable.
		"""
		self.calculate_totals()
		remaining = abs(flt(self.net_total))
		rows = []
		if remaining <= 0:
			return rows

		for inv in self.fetch_open_invoices_for_credit_note():
			if remaining <= 0:
				break
			allocate = min(remaining, flt(inv.invoice_amount))
			rows.append(
				{
					"purchase_invoice": inv.name,
					"bill_no": inv.bill_no,
					"posting_date": inv.posting_date,
					"invoice_amount": inv.invoice_amount,
					"allocated_amount": allocate,
				}
			)
			remaining -= allocate

		return rows

	@frappe.whitelist()
	def build_credit_note_items_from_allocations(self):
		"""Build the debit-note item lines from the allocated invoices.

		For each allocation, the target invoice's return lines (via ``make_return_doc``,
		as the previous single-invoice flow did) are scaled by
		``allocated_amount / invoice line total`` so the resulting item totals match what
		is being allocated. Returns the proposed rows without mutating the document; the
		front-end fills the items grid.
		"""
		from erpnext.controllers.sales_and_purchase_return import make_return_doc

		items = []
		currency = None
		for row in self.credit_note_allocations:
			allocated = flt(row.allocated_amount)
			if allocated <= 0:
				continue

			return_doc = make_return_doc("Purchase Invoice", row.purchase_invoice)
			currency = currency or return_doc.currency

			# Distribute the allocated amount across the invoice's return lines in
			# proportion to their value, so the built lines sum to exactly the allocated
			# amount (allocating 329 yields a 329 line, not a tax-adjusted figure).
			line_total = sum(abs(flt(item.amount)) for item in return_doc.items)
			if line_total <= 0:
				continue
			ratio = allocated / line_total

			for item in return_doc.items:
				items.append(
					{
						"item_code": item.item_code,
						"description": item.description,
						# make_return_doc already carries negative quantities; scale the value
						# through the rate so the sign and per-item detail are preserved.
						"qty": flt(item.qty),
						"rate": flt(item.rate) * ratio,
						"amount": flt(item.amount) * ratio,
						"expense_account": item.expense_account,
						"cost_center": item.cost_center,
						"project": item.project,
						"item_tax_template": item.item_tax_template,
					}
				)

		return {"items": items, "currency": currency}

	def reconcile_credit_note_allocations(self, purchase_invoice):
		"""Allocate the submitted credit note ``purchase_invoice`` across the target
		invoices listed in ``credit_note_allocations`` using ERPNext's Payment
		Reconciliation engine. Only submitted target invoices are reconciled; drafts
		are skipped with a comment.
		"""
		from erpnext.accounts.party import get_party_account

		if not self.credit_note_allocations or purchase_invoice.docstatus != 1:
			return

		targets = []
		for row in self.credit_note_allocations:
			if flt(row.allocated_amount) <= 0:
				continue
			if frappe.db.get_value("Purchase Invoice", row.purchase_invoice, "docstatus") != 1:
				self.add_comment(
					text=_(
						"Invoice {0} is not submitted and was skipped during credit note reconciliation."
					).format(row.purchase_invoice)
				)
				continue
			targets.append(row)

		if not targets:
			return

		pr = frappe.new_doc("Payment Reconciliation")
		pr.company = self.company
		pr.party_type = "Supplier"
		pr.party = self.supplier
		pr.receivable_payable_account = get_party_account("Supplier", self.supplier, self.company)
		pr.get_unreconciled_entries()

		pay_doc = next((p for p in pr.payments if p.get("reference_name") == purchase_invoice.name), None)
		if not pay_doc:
			self.add_comment(
				text=_("Credit note {0} has no outstanding balance to allocate.").format(
					purchase_invoice.name
				)
			)
			return

		# Work on plain dicts: the reconciliation engine helpers mutate these entries.
		pay = pay_doc.as_dict()
		invoices_by_name = {inv.get("invoice_number"): inv.as_dict() for inv in pr.invoices}
		invoice_exchange_map = pr.get_invoice_exchange_map(pr.invoices, pr.payments)
		default_exc_gain_loss = frappe.get_cached_value("Company", self.company, "exchange_gain_loss_account")

		pay["unreconciled_amount"] = pay.get("amount")
		pay["exchange_rate"] = invoice_exchange_map.get(pay.get("reference_name"))
		remaining = abs(flt(pay.get("amount")))

		allocations = []
		for row in targets:
			if remaining <= 0:
				break

			inv = invoices_by_name.get(row.purchase_invoice)
			if not inv:
				# Fully paid (or otherwise settled) invoice: nothing left to reconcile
				# against, so the debit note keeps this portion as an open credit.
				self.add_comment(
					text=_("Invoice {0} has no outstanding amount and was skipped.").format(
						row.purchase_invoice
					)
				)
				continue

			# Never reconcile more than the invoice's own outstanding, even when the
			# requested allocation (based on the invoice amount) is larger.
			allocate = min(flt(row.allocated_amount), remaining, flt(inv.get("amount")))
			if allocate <= 0:
				continue

			pay["amount"] = remaining
			inv["exchange_rate"] = invoice_exchange_map.get(inv.get("invoice_number"))
			entry = pr.get_allocated_entry(pay, inv, allocate)
			entry.difference_amount = pr.get_difference_amount(pay, inv, allocate)
			entry.difference_account = default_exc_gain_loss
			entry.exchange_rate = inv.get("exchange_rate")
			entry.update({"gain_loss_posting_date": pay.get("posting_date")})
			allocations.append(entry)
			remaining -= allocate

		if not allocations:
			return

		pr.set("allocation", [])
		for entry in allocations:
			pr.append("allocation", entry)

		pr.reconcile()
		self.add_comment(
			text=_("Credit note {0} reconciled against {1} invoice(s).").format(
				purchase_invoice.name, len(allocations)
			)
		)

	def auto_reconcile(self):
		if self.status in ["Completed", "Closed"] or not self.items:
			return

		if (not self.purchase_order_number and not self.is_return) or not self.net_total:
			return

		settings: eTransactionsSettings = frappe.get_single("eTransactions Settings")  # type: ignore
		if not settings.reconcile_with_purchase_receipts:  # type: ignore
			return

		if frappe.db.exists("Purchase Invoice", dict(supplier_invoice=self.name, docstatus=("!=", 2))):
			return

		if any(states_its_own_amount(item) for item in self.items):
			# The purchase invoice this would book recomputes every line as quantity x unit
			# price and drops these back to zero, posting the wrong payable. ERPNext has no
			# representation for such a line, so leave the call to a human.
			self.add_comment(
				text=_(
					"The automatic reconciliation was skipped because a line with no unit price states its own amount, which a purchase invoice cannot reproduce."
				)
			)
			return

		pending_invoicing_amount = self.get_pending_invoicing_amount()

		# Do not automatically submit if amount do not match
		max_amount = min(
			flt(pending_invoicing_amount) + flt(settings.max_difference_amount),
			flt(pending_invoicing_amount) * (1 + flt(settings.max_difference_percentage_on_net_total) / 100),
		)

		precision = frappe.db.get_default("currency_precision")

		if flt(self.net_total, precision=precision) <= flt(max_amount, precision=precision):  # type: ignore
			self.calculate_totals()

			net_total = (
				abs(flt(self.net_total, precision=precision))
				if self.is_return
				else flt(self.net_total, precision=precision)
			)  # type: ignore
			if flt(self.supplier_net_amount, precision=precision) == net_total:  # type: ignore
				try:
					doc = self.create_purchase_invoice(submit=settings.auto_submit_purchase_invoices)  # type: ignore
					self.add_comment(
						text=_(
							"Purchase invoice {0} has been automatically created for this invoice."
						).format(doc.name)
					)
				except Exception as e:
					self.add_comment(text=str(e))
					raise e
			else:
				self.add_comment(
					text=_("The automatic reconciliation has failed because the totals do not match")
				)

			self.commit_totals()
			self.set_status()
		else:
			self.add_comment(
				text=_(
					"The automatic reconciliation has failed because the net total is higher than {0}"
				).format(fmt_money(max_amount, currency=self.currency))
			)

	def get_pending_invoicing_amount(self):
		total_per_ref = defaultdict(dict)
		for item in self.items:
			if (
				item.reference_doctype
				and item.reference_docname
				and (item.reference_doctype, item.reference_docname) not in total_per_ref
			):
				doc = frappe.get_doc(item.reference_doctype, item.reference_docname)
				total_per_ref[(item.reference_doctype, item.reference_docname)] = doc.net_total - (
					flt(doc.per_billed) / 100.0 * doc.net_total
				)

		return sum(total_per_ref.values())


@frappe.whitelist()
def get_item_details(row, company, tax_category=None):
	from erpnext.accounts.doctype.budget.budget import get_item_details as _get_item_details
	from erpnext.stock.get_item_details import get_item_tax_template

	row = frappe.parse_json(row)
	item_code = row.get("item_code")
	item = frappe.get_cached_doc("Item", item_code)

	cost_center, expense_account = _get_item_details(
		frappe._dict({"item_code": item_code, "company": company})
	)

	description = frappe.db.get_value("Item", item_code, "description")

	ctx: ItemDetailsCtx = {
		"company": company,
		"tax_category": tax_category,
		"base_net_rate": row.get("base_rate"),  # type: ignore
		"doctype": "Purchase Invoice",
		"child_doctype": "Purchase Invoice Item",
	}

	out = ItemDetails()
	get_item_tax_template(ctx, item, out)
	return {
		"cost_center": cost_center,
		"expense_account": expense_account,
		"description": description,
		"item_tax_template": out.get("item_tax_template"),
	}


def states_its_own_amount(row) -> bool:
	"""True for a line that carries a net amount but no unit price to rebuild it from.

	Suppliers state discounts and credits this way (BT-131 / BT-146), and
	`calculate_taxes_and_totals` recomputes every amount as qty * rate, destroying them.

	Narrow on purpose: the general `qty * rate != amount` also matches a line-level
	allowance (BT-136) that keeps a real unit price, where a stale `amount` left by an edit
	to `rate` is indistinguishable from a stated one. With no rate, the amount is all the
	line has.
	"""
	return not flt(row.get("rate")) and bool(flt(row.get("amount")))


def unit_price_exceeds_precision(row, precision: int) -> bool:
	"""True for a line whose unit price has more decimals than a currency field keeps.

	Surcharges are billed this way (563.71 kg at 0.015 = 8.46), and
	`calculate_taxes_and_totals` rounds the rate before multiplying (0.02 gives 11.27).

	The amount must still equal qty * rate at full precision, which keeps out the
	stale `amount` described in `states_its_own_amount`.
	"""
	rate, amount = flt(row.get("rate")), flt(row.get("amount"))
	return (
		bool(amount)
		and rate != flt(rate, precision)
		and flt(flt(row.get("qty")) * rate, precision) == flt(amount, precision)
	)


def get_best_match_from_list_of_dicts(data, matching_element, key):
	if best_match := next(
		iter(
			sorted(
				data,
				key=lambda doc: difflib.SequenceMatcher(
					lambda doc: doc == " ", doc.get(key).lower(), matching_element.lower()
				).ratio(),
				reverse=True,
			)
		)
	):
		return best_match

	return {}


def make_purchase_order(source_name, target_doc=None, ignore_permissions=False):
	from erpnext.buying.doctype.purchase_order.mapper import set_missing_values
	from frappe.model.mapper import get_mapped_doc

	def purchase_invoice_item_condition(doc):
		if not doc.reference_doctype:
			return doc
		else:
			return {}

	def postprocess(source, target_doc):
		target_doc.ignore_pricing_rule = 1

		set_missing_values(source, target_doc)

		if not target_doc.schedule_date:
			target_doc.schedule_date = frappe.utils.nowdate()

		# target_doc.payment_schedule = []
		target_doc.supplier_invoice = source_name
		target_doc.department = source.get("department")

		target_doc.set("taxes", [])

		# append taxes
		if target_doc.taxes_and_charges:
			TaxService(target_doc).append_taxes_from_master()
		else:
			TaxService(target_doc).append_taxes_from_item_tax_template()

		target_doc.run_method("set_missing_values")
		target_doc.run_method("calculate_taxes_and_totals")

	def update_source_item(obj, target, source_parent):
		target.supplier_invoice_item = obj.name

	doclist = get_mapped_doc(
		"Supplier Invoice",
		source_name,
		{
			"Supplier Invoice": {
				"doctype": "Purchase Order",
			},
			"Supplier Invoice Item": {
				"doctype": "Purchase Order Item",
				"postprocess": update_source_item,
				"condition": purchase_invoice_item_condition,
			},
		},
		target_doc,
		postprocess,
		ignore_permissions=ignore_permissions,
	)

	return doclist


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def get_purchase_documents(doctype, txt, searchfield, start, page_len, filters):
	fields = ["name", "supplier", "grand_total", "status"]
	if doctype == "Purchase Order":
		fields.append("transaction_date")
	elif doctype == "Purchase Receipt":
		fields.append("posting_date")

	if txt:
		filters["name"] = ("like", f"%{txt}%")

	return frappe.get_list(doctype, filters=filters, fields=fields)


@frappe.whitelist()
def get_documents_child_items(doctype, filters, limit_page_length):
	query_filters = frappe.parse_json(filters)
	if not [f for f in query_filters if f[0] == "parent"]:
		query_filters.append(["parent", "in", []])

	purchase_doc_dt = frappe.qb.DocType(doctype)
	purchase_doc_item_dt = frappe.qb.DocType(f"{doctype} Item")

	query = frappe.qb.get_query(
		table=f"{doctype} Item",
		filters=query_filters,
		fields=["name", "parent"],
		limit=cint(limit_page_length),
	)

	query = (
		query.left_join(purchase_doc_dt)
		.on(purchase_doc_item_dt.parent == purchase_doc_dt.name)
		.select(purchase_doc_dt.supplier)
	)

	if doctype == "Purchase Order":
		query = query.select(purchase_doc_dt.transaction_date)
	elif doctype == "Purchase Receipt":
		query = query.select(purchase_doc_dt.posting_date)

	query = query.select(
		purchase_doc_item_dt.item_code,
		purchase_doc_item_dt.qty,
		purchase_doc_item_dt.net_amount,
		purchase_doc_item_dt.cost_center,
	)

	query = query.where(purchase_doc_item_dt.billed_amt < purchase_doc_item_dt.net_amount)

	if doctype == "Purchase Order":
		query = query.orderby(purchase_doc_dt.transaction_date, order=Order.desc)
	elif doctype == "Purchase Receipt":
		query = query.orderby(purchase_doc_dt.posting_date, order=Order.desc)

	return query.run(as_dict=True)


def register_purchase_order_items(doc, method=None):
	if not doc.supplier_invoice:
		return

	for item in doc.items:
		if item.supplier_invoice_item:
			if not frappe.db.get_value("Supplier Invoice Item", item.supplier_invoice_item, "row"):
				frappe.db.set_value("Supplier Invoice Item", item.supplier_invoice_item, "row", item.name)
				frappe.db.set_value(
					"Supplier Invoice Item", item.supplier_invoice_item, "reference_doctype", item.parenttype
				)
				frappe.db.set_value(
					"Supplier Invoice Item", item.supplier_invoice_item, "reference_docname", item.parent
				)


def auto_match_with_purchase_receipt(doc, method=None):
	supplier_invoices = frappe.get_list(
		"Supplier Invoice",
		filters={
			"supplier": doc.supplier,
			"status": "Pending",
			"purchase_order_number": ("is", "set"),
		},
		order_by="bill_date ASC",
		fields=["name", "supplier_net_amount"],
	)

	exact_match = [ppi for ppi in supplier_invoices if doc.net_total == ppi.supplier_net_amount]
	if exact_match:
		supplier_invoices = exact_match[:1]

	for supplier_invoice in supplier_invoices:
		ppi: SupplierInvoice = frappe.get_doc("Supplier Invoice", supplier_invoice.name)  # type: ignore
		ppi.flags.ignore_permissions = True
		ppi.save()


def remove_link_with_supplier_invoices(doc, method=None):
	if method not in ["on_change", "on_cancel"]:
		return

	if method == "on_change" and doc.status != "Closed":
		return

	for supplier_invoice in frappe.get_list(
		"Supplier Invoice",
		filters={
			"supplier": doc.supplier,
			"status": "Pending",
			"purchase_order_number": ("is", "set"),
		},
	):
		ppi: SupplierInvoice = frappe.get_doc("Supplier Invoice", supplier_invoice.name)  # type: ignore
		items = [item.reference_docname for item in ppi.items if item.reference_doctype == "Purchase Receipt"]
		if doc.name in items:
			ppi.items = []
		ppi.flags.ignore_permissions = True
		ppi.save()


def set_pending_purchase_order_status(doc, method=None):
	if not doc.supplier_invoice:
		return

	ppi: SupplierInvoice = frappe.get_doc("Supplier Invoice", doc.supplier_invoice)  # type: ignore
	ppi.run_method("set_status", commit=True)
	ppi.notify_update()


def update_guide_status_from_payment(doc, method=None):
	"""A payment changes a booked invoice into a paid one."""
	for ref in doc.get("references", []):
		if ref.reference_doctype != "Purchase Invoice":
			continue
		if supplier_invoice := frappe.db.get_value(
			"Purchase Invoice", ref.reference_name, "supplier_invoice"
		):
			update_guide_status(supplier_invoice)


def update_guide_status_from_lifecycle_event(doc, method=None):
	"""A status reported on the platform (by us or the supplier) can dispute or refuse the invoice."""
	if not doc.einvoice:
		return
	for name in frappe.get_all("Supplier Invoice", filters={"einvoice": doc.einvoice}, pluck="name"):
		update_guide_status(name)


def deduplicate_items(items):
	po_detail = set()
	pr_detail = set()

	output = []

	for item in items:
		if item.po_detail and item.po_detail in po_detail:
			continue
		elif item.po_detail:
			po_detail.add(item.po_detail)

		if item.pr_detail and item.pr_detail in pr_detail:
			continue
		elif item.pr_detail:
			pr_detail.add(item.pr_detail)

		output.append(item)

	return output


def cites_reference(text: str | None, *references: str | None) -> bool:
	"""Whether `text` cites one of `references` as a whole word.

	Blank references are skipped: an empty pattern matches at any word boundary, so every
	open order without a confirmation number used to match every OCR line.
	"""
	if not text:
		return False
	for reference in references:
		reference = (reference or "").strip()
		if reference and re.search(
			r"(?<![\w\d])" + re.escape(reference) + r"(?![\w\d])", text, re.IGNORECASE
		):
			return True
	return False


def validate_total(doc, method):
	if not doc.supplier_invoice:
		return

	if frappe.db.get_single_value("eTransactions Settings", "block_if_grand_total_exceeds_pending_pi"):
		if doc.grand_total > frappe.db.get_value(
			"Supplier Invoice", doc.supplier_invoice, "supplier_grand_total"
		):
			frappe.throw(
				_(
					"The invoice grand total exceeds the supplier provided grand total. You are not allowed to create this purchase invoice."
				)
			)

	if frappe.db.get_single_value("eTransactions Settings", "block_if_net_total_exceeds_pending_pi"):
		if doc.net_total > frappe.db.get_value(
			"Supplier Invoice", doc.supplier_invoice, "supplier_net_amount"
		):
			frappe.throw(
				_(
					"The invoice net total exceeds the supplier provided net total. You are not allowed to create this purchase invoice."
				)
			)


@frappe.whitelist()
def create_purchase_invoice(docname: str, submit: bool | str | None = False):
	return frappe.get_doc("Supplier Invoice", docname).run_method(
		"create_purchase_invoice", submit=sbool(submit)
	)


@frappe.whitelist()
def create_purchase_order(
	docname: str, transaction_date: str | None = None, submit: bool | str | None = False
):
	return frappe.get_doc("Supplier Invoice", docname).run_method(
		"create_purchase_order", transaction_date=transaction_date, submit=sbool(submit)
	)


@frappe.whitelist()
def retry_supplier_match(invoices: list | str) -> int:
	"""Re-run supplier resolution over a selection of invoices.

	This is a machine guess, not a user confirmation: the invoices are saved with
	`flags.automatic_supplier_match` so the result keeps the confidence the resolver
	computed and is never learned as an alias.
	"""
	if isinstance(invoices, str):
		invoices = frappe.parse_json(invoices)

	resolver = InvoiceEntityResolverMixin()
	matched = 0

	for name in invoices:
		doc: SupplierInvoice = frappe.get_doc("Supplier Invoice", name)  # type: ignore
		doc.flags.automatic_supplier_match = True

		vendor_name = None
		if doc.ocr_request:
			raw = frappe.db.get_value("OCR Request", doc.ocr_request, "analysis")
			vendor_name = (frappe.parse_json(raw) or {}).get("VENDOR_NAME") if raw else None

		supplier = resolver.resolve_supplier(
			seller_name=vendor_name,
			tax_id=doc.tax_id,
			iban=doc.vendor_iban,
		)

		if supplier:
			doc.supplier = supplier
			doc.match_confidence = getattr(resolver, "_match_confidence", None) or "low"
		else:
			doc.get_supplier()

		if doc.supplier:
			doc.flags.ignore_permissions = True
			doc.save()
			matched += 1

	return matched


@frappe.whitelist()
def get_settings():
	settings = frappe.get_single("eTransactions Settings")
	return {
		"reconcile_with_purchase_receipts": settings.reconcile_with_purchase_receipts  # type: ignore
	}


@frappe.whitelist()
def make_purchase_invoice_from_pr(
	source_name: str, target_doc: "PurchaseInvoice | None" = None, args: str | None = None
):  # TODO: find a better way to handle this in ERPNext directly
	from erpnext.stock.doctype.purchase_receipt.mapper import get_invoiced_qty_map, get_returned_qty_map

	if args is None:
		args = {}
	if isinstance(args, str):
		args = json.loads(args)

	from erpnext.accounts.party import get_payment_terms_template

	doc = frappe.get_doc("Purchase Receipt", source_name)
	returned_qty_map = get_returned_qty_map(source_name)
	invoiced_qty_map = get_invoiced_qty_map(source_name)

	def set_missing_values(source, target):
		if len(target.get("items")) == 0:
			frappe.throw(_("All items have already been Invoiced/Returned"))

		doc: SalesInvoice = frappe.get_doc(target)  # type: ignore
		doc.payment_terms_template = get_payment_terms_template(source.supplier, "Supplier", source.company)
		doc.run_method("onload")
		doc.run_method("set_missing_values")

		if args and args.get("merge_taxes"):
			merge_taxes(source.get("taxes") or [], doc)

		doc.run_method("calculate_taxes_and_totals")
		PaymentScheduleService(doc).set_payment_schedule()

	def update_item(source_doc, target_doc, source_parent):
		target_doc.qty, returned_qty = get_pending_qty(source_doc)
		if frappe.db.get_single_value("Buying Settings", "bill_for_rejected_quantity_in_purchase_invoice"):
			target_doc.rejected_qty = 0
		target_doc.stock_qty = flt(target_doc.qty) * flt(
			target_doc.conversion_factor, target_doc.precision("conversion_factor")
		)
		returned_qty_map[source_doc.name] = returned_qty

	def get_pending_qty(item_row):
		qty = item_row.qty
		if frappe.db.get_single_value("Buying Settings", "bill_for_rejected_quantity_in_purchase_invoice"):
			qty = item_row.received_qty

		pending_qty = qty - invoiced_qty_map.get(item_row.name, 0)

		if frappe.db.get_single_value("Buying Settings", "bill_for_rejected_quantity_in_purchase_invoice"):
			return pending_qty, 0

		returned_qty = flt(returned_qty_map.get(item_row.name, 0))
		if item_row.rejected_qty and returned_qty:
			returned_qty -= item_row.rejected_qty

		if returned_qty:
			if returned_qty >= pending_qty:
				returned_qty -= pending_qty
				pending_qty = 0
			else:
				pending_qty -= returned_qty
				returned_qty = 0

		if (
			qty == 1 and item_row.billed_amt <= item_row.net_amount
		):  # @dokos: allow creating invoices based on the billed_amt
			pending_qty = 1

		return pending_qty, returned_qty

	def select_item(d):
		filtered_items = args.get("filtered_children", [])
		child_filter = d.name in filtered_items if filtered_items else True
		return child_filter

	doclist = get_mapped_doc(
		"Purchase Receipt",
		source_name,
		{
			"Purchase Receipt": {
				"doctype": "Purchase Invoice",
				"field_map": {
					"supplier_warehouse": "supplier_warehouse",
					"is_return": "is_return",
					"bill_date": "bill_date",
				},
				"validation": {
					"docstatus": ["=", 1],
				},
			},
			"Purchase Receipt Item": {
				"doctype": "Purchase Invoice Item",
				"field_map": {
					"name": "pr_detail",
					"parent": "purchase_receipt",
					"qty": "received_qty",
					"purchase_order_item": "po_detail",
					"purchase_order": "purchase_order",
					"is_fixed_asset": "is_fixed_asset",
					"asset_location": "asset_location",
					"asset_category": "asset_category",
					"wip_composite_asset": "wip_composite_asset",
				},
				"postprocess": update_item,
				"filter": lambda d: (
					get_pending_qty(d)[0] <= 0 if not doc.get("is_return") else get_pending_qty(d)[0] > 0
				),
				"condition": select_item,
			},
			"Purchase Taxes and Charges": {
				"doctype": "Purchase Taxes and Charges",
				"reset_value": not (args and args.get("merge_taxes")),
				"ignore": args.get("merge_taxes") if args else 0,
			},
		},
		target_doc,
		set_missing_values,
	)

	return doclist
