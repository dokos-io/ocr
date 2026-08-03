# Copyright (c) 2026, ALYF GmbH, Dokos SAS and contributors
# For license information, please see license.txt

from typing import TYPE_CHECKING

import frappe
from erpnext import get_default_company
from erpnext.edi.doctype.code_list.code_list import get_docnames_for

from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from etransactions.controllers.entity_resolver import InvoiceEntityResolverMixin
from etransactions.etransactions.doctype.einvoice.parser import eInvoiceParser
from etransactions.etransactions.doctype.einvoice.generator import (
	EInvoiceGenerator,
	EInvoiceMapper,
	resolve_syntax,
)
from etransactions.schematron import get_validation_errors
from etransactions.utils import EInvoiceProfile, get_drafthorse_schema
from etransactions.utils.files import copy_file_to_document


if TYPE_CHECKING:
	from erpnext.stock.doctype.item.item import Item
	from erpnext.accounts.doctype.sales_invoice.sales_invoice import SalesInvoice
	from frappe.core.doctype.file.file import File


class eInvoice(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from etransactions.etransactions.doctype.einvoice_item.einvoice_item import eInvoiceItem
		from etransactions.etransactions.doctype.einvoice_payment_term.einvoice_payment_term import eInvoicePaymentTerm
		from etransactions.etransactions.doctype.einvoice_trade_tax.einvoice_trade_tax import eInvoiceTradeTax
		from frappe.types import DF

		allowance_total: DF.Currency
		amended_from: DF.Link | None
		billing_period_end: DF.Date | None
		billing_period_start: DF.Date | None
		buyer_address_line_1: DF.Data | None
		buyer_address_line_2: DF.Data | None
		buyer_city: DF.Data | None
		buyer_country: DF.Link | None
		buyer_electronic_address: DF.Data | None
		buyer_electronic_address_scheme: DF.Data | None
		buyer_name: DF.Data | None
		buyer_postcode: DF.Data | None
		buyer_reference: DF.Data | None
		charge_total: DF.Currency
		company: DF.Link | None
		contract_reference: DF.Data | None
		currency: DF.Link | None
		due_date: DF.Date | None
		due_payable: DF.Currency
		e_invoice_is_correct: DF.Check
		einvoice: DF.Link | None
		einvoice_type: DF.Literal["Incoming", "Outgoing"]
		einvoice_xml: DF.HTMLEditor | None
		grand_total: DF.Currency
		id: DF.Data | None
		issue_date: DF.Date | None
		items: DF.Table[eInvoiceItem]
		line_total: DF.Currency
		payee_account_name: DF.Data | None
		payee_bic: DF.Data | None
		payee_iban: DF.Data | None
		payment_terms: DF.Table[eInvoicePaymentTerm]
		profile: DF.ReadOnly | None
		purchase_order: DF.Link | None
		sales_invoice: DF.Link | None
		seller_address_line_1: DF.Data | None
		seller_address_line_2: DF.Data | None
		seller_city: DF.Data | None
		seller_country: DF.Link | None
		seller_electronic_address: DF.Data | None
		seller_electronic_address_scheme: DF.Data | None
		seller_name: DF.Data | None
		seller_postcode: DF.Data | None
		seller_tax_id: DF.Data | None
		supplier_invoices_basket: DF.Link | None
		syntax: DF.Literal["CII", "UBL"]
		tax_basis_total: DF.Currency
		tax_total: DF.Currency
		taxes: DF.Table[eInvoiceTradeTax]
		total_prepaid: DF.Currency
		validation_errors: DF.Text | None
		validation_warnings: DF.Text | None
	# end: auto-generated types

	def validate(self):
		if self.einvoice_type == "Incoming":
			self.validate_incoming_data()
		elif self.einvoice_type == "Outgoing":
			self.create_outgoing_einvoice()
			self.validate_einvoice()

	def after_insert(self):
		# Claim the lifecycle events that were polled before this invoice existed.
		if self.einvoice_type == "Incoming" and self.pa_flow_id:
			from etransactions.etransactions.doctype.einvoice_event.einvoice_event import (
				adopt_orphan_events,
			)

			adopt_orphan_events(self.name, self.pa_flow_id)

	def on_update(self):
		# A flow whose original file has not been downloaded yet carries only the
		# platform's metadata; building a Supplier Invoice from it would produce an
		# empty draft. Wait until fetch_content_from_platform() has parsed the file.
		if self.pa_content_state == "pending":
			return
		if not frappe.db.get_value("Supplier Invoice", dict(einvoice=self.name)):
			self.generate_supplier_invoice()

	def validate_incoming_data(self):
		self.read_values_from_einvoice()
		self.guess_company()
		self.guess_uom()
		self.guess_po_details()

	def create_outgoing_einvoice(self):
		self.einvoice_data = None
		self.map_sales_invoice_to_einvoice()
		self.generate_einvoice()

	def map_sales_invoice_to_einvoice(self):
		self.einvoice_data: EInvoiceMapper = EInvoiceMapper(self)
		self.einvoice_data.run()

	def generate_einvoice(self):
		if not hasattr(self, "einvoice_data") or not self.einvoice_data:
			return

		sales_invoice: SalesInvoice = self.einvoice_data.sales_invoice
		sales_invoice.run_method("before_einvoice_generation")

		profile = EInvoiceProfile(sales_invoice.get("etransaction_profile"))
		self.syntax = resolve_syntax(self, sales_invoice)

		generator_kwargs = dict(
			profile=profile,
			einvoice=self,
			company=self.einvoice_data.company,
			customer=self.einvoice_data.customer,
			seller_address=self.einvoice_data.seller_address,
			buyer_address=self.einvoice_data.buyer_address,
			shipping_address=self.einvoice_data.shipping_address,
			seller_contact=self.einvoice_data.seller_contact,
			buyer_contact=self.einvoice_data.buyer_contact,
		)

		if self.syntax == "UBL":
			from etransactions.etransactions.doctype.einvoice.ubl_generator import UBLGenerator

			generator = UBLGenerator(**generator_kwargs)
			generator.create_einvoice()
			self.einvoice_data.sales_invoice.run_method("after_einvoice_generation")
			self.einvoice_xml = generator.serialize()
			return

		generator = EInvoiceGenerator(**generator_kwargs)
		generator.create_einvoice()
		doc = generator.get_einvoice()

		self.einvoice_data.sales_invoice.run_method("after_einvoice_generation")

		self.einvoice_xml = doc.serialize(schema=get_drafthorse_schema(profile))

	def on_submit(self):
		self.add_seller_product_ids_to_items()

	def on_trash(self):
		if self.pa_flow_id:
			frappe.throw(
				_("Cannot delete an eInvoice that has been submitted to the accredited platform (Flow ID: {0}).").format(self.pa_flow_id)
			)

	@frappe.whitelist()
	def send_to_plateform(self):
		"""Submit this outgoing eInvoice to the accredited platform."""
		self.check_permission("write")
		if self.einvoice_type != "Outgoing":
			frappe.throw(_("Only Outgoing eInvoices can be submitted to the accredited platform."))
		# A healthy flow can't be re-sent. An errored or rejected flow may be
		# resubmitted to retry after fixing the cause.
		if self.pa_flow_id and self.pa_status not in ("error", "rejected"):
			frappe.throw(_("This eInvoice has already been submitted to the accredited platform (Flow ID: {0}).").format(self.pa_flow_id))

		# Guard against concurrent sends (enqueued auto-send racing a manual click):
		# take a row lock and re-read, so only one submission can pass this point.
		locked = frappe.db.get_value("eInvoice", self.name, ["pa_flow_id", "pa_status"], for_update=True, as_dict=True)
		if locked and locked.pa_flow_id and locked.pa_status not in ("error", "rejected"):
			frappe.throw(_("This eInvoice has already been submitted to the accredited platform."))

		# A B2C invoice's buyer isn't reachable through the e-invoicing directory, so it
		# is declared via e-reporting rather than submitted as a structured invoice. The
		# auto-send path already filters these out; block the manual button here too so a
		# user can't push one into the invoice endpoint (the platform would reject it with
		# an opaque "receiver address does not exist in directory" error).
		if self.pa_processing_rule == "B2C":
			frappe.throw(
				_(
					"This invoice is classified B2C: the customer is not reachable through the "
					"e-invoicing directory, so the sale is declared to the tax authority via "
					"e-reporting, not submitted as a structured e-invoice.<br><br>"
					"To send a structured invoice instead, register the customer in the directory "
					"(set a valid SIREN and re-sync the directory) so an active routing line is "
					"resolved — the invoice will then be classified B2B."
				),
				frappe.ValidationError,
				title=_("B2C invoice — cannot be submitted to the platform"),
			)

		if not self.seller_electronic_address:
			frappe.throw(
				_(
					"The seller's electronic address (BT-34) is missing from this eInvoice. "
					"Set an email on the Company record, or configure the Electronic Address fields "
					"(etransactions_electronic_address_scheme / etransactions_electronic_address) "
					"on the Company, then re-save the Sales Invoice to regenerate the eInvoice."
				)
			)

		from etransactions.plateforme_agreee.session import get_client

		customer = None
		if self.sales_invoice:
			customer = frappe.db.get_value("Sales Invoice", self.sales_invoice, "customer")

		client = get_client(self.company, customer=customer)
		file_content, filename, syntax = self._get_file_for_pa()
		processing_rule = self.pa_processing_rule or "B2B"

		result = client.submit_invoice(
			file_content,
			filename,
			syntax,
			external_id=self.sales_invoice,
			processing_rule=processing_rule,
		)

		# Use db_set to avoid re-triggering validate() which regenerates the XML
		self.db_set({
			"pa_flow_id": result.flow_id,
			"pa_submitted_at": result.submitted_at,
			"pa_updated_at": result.submitted_at,
			"pa_status": "sent",
			"pa_syntax": result.syntax,
			"pa_flow_type": result.flow_type,
			# Clear any error text from a previous (rejected) send on a successful resend.
			"pa_error_details": None,
		})

	@frappe.whitelist()
	def refresh_pa_status(self):
		"""Poll the accredited platform for the latest flow state."""
		self.check_permission("read")
		if not self.pa_flow_id:
			frappe.throw(_("This eInvoice has not been submitted to the accredited platform yet."))

		from etransactions.plateforme_agreee.session import get_client

		customer = None
		if self.sales_invoice:
			customer = frappe.db.get_value("Sales Invoice", self.sales_invoice, "customer")

		client = get_client(self.company, customer=customer)
		status = client.get_invoice_status(self.pa_flow_id)

		update = {}
		if status.status:
			update["pa_status"] = status.status
		if status.updated_at:
			update["pa_updated_at"] = status.updated_at
		if status.error_details:
			update["pa_error_details"] = status.error_details
		elif status.status and status.status not in ("error", "rejected"):
			# Recovered flow: drop any stale error text from a previous poll.
			update["pa_error_details"] = None

		if update:
			self.db_set(update)

	def lifecycle_transition_error(self, status: str) -> str | None:
		"""Why ``status`` cannot be reported for this invoice right now, or ``None``.

		Non-throwing, so the automatic senders can consult the same rules the manual
		path enforces and skip quietly instead of failing.
		"""
		from etransactions.plateforme_agreee import lifecycle_status
		from etransactions.etransactions.doctype.einvoice_event.einvoice_event import (
			current_lifecycle_state,
		)

		return lifecycle_status.transition_error(current_lifecycle_state(self.name), status)

	@frappe.whitelist()
	def submit_lifecycle_status(
		self,
		status: str,
		comment: str | None = None,
		reason_code: str | None = None,
		reason_text: str | None = None,
		amount: float | None = None,
		currency: str | None = None,
		payment_date: str | None = None,
		origin: str = "Manual",
	):
		"""Report an invoice lifecycle status to the accredited platform.

		``status`` is a canonical status (etransactions.plateforme_agreee.lifecycle_status).
		"""
		from etransactions.plateforme_agreee import lifecycle_status
		from etransactions.plateforme_agreee.session import get_client
		from etransactions.etransactions.doctype.einvoice_event.einvoice_event import record_event
		from etransactions.etransactions.doctype.einvoicing_log.einvoicing_log import eInvoicingLog

		self.check_permission("write")
		if not self.pa_flow_id:
			frappe.throw(_("This eInvoice has not been submitted to the accredited platform yet."))
		if status not in lifecycle_status.STATUSES:
			frappe.throw(_("Unknown lifecycle status '{0}'.").format(status))

		if lifecycle_status.reason_required(status):
			if not reason_code:
				frappe.throw(_("A reason code is required to report the status '{0}'.").format(lifecycle_status.label(status)))
			if reason_code not in lifecycle_status.reason_codes(status):
				frappe.throw(_("'{0}' is not a valid reason code for the status '{1}'.").format(reason_code, lifecycle_status.label(status)))
			reason_text = reason_text or reason_code

		# The lifecycle is a state machine: a status that contradicts or merely repeats
		# what has already been reported must not reach the platform. Checked here
		# rather than at the call sites because this method is the single choke point
		# for every outbound send (manual UI, automatic hooks, guided cancellation).
		# Inbound polled events go straight to record_event and are never gated: the
		# history must stay a faithful log of what the platform said, contradictions
		# included.
		if error := self.lifecycle_transition_error(status):
			frappe.throw(error, title=_("Lifecycle status not allowed"))

		details = None
		if reason_code or reason_text or comment or amount is not None:
			details = [{
				"reason_code": reason_code,
				"reason_text": reason_text,
				"comment": comment,
				"amount": amount,
				"currency": currency,
				"payment_date": payment_date,
			}]

		customer = None
		if self.sales_invoice:
			customer = frappe.db.get_value("Sales Invoice", self.sales_invoice, "customer")
		transaction_type = "sales" if self.einvoice_type == "Outgoing" else "purchases"
		client = get_client(self.company, customer=customer, transaction_type=transaction_type)

		result = {
			"operation_type": "lifecycle_send",
			"origin": origin,
			"company": self.company,
			"new_count": 0,
			"updated_count": 0,
			"logs": [],
		}

		try:
			res = client.submit_lifecycle_status(
				flow_id=self.pa_flow_id,
				status=status,
				einvoice=self,
				details=details,
			)
		except Exception as e:
			result["logs"].append(("error", f"Failed to send status '{status}' for eInvoice {self.name}: {str(e)}"))
			eInvoicingLog.create_log(result)
			raise

		record_event(
			self.name,
			direction="out",
			status=status,
			state=res.state,
			pa_event_id=res.event_id,
			pa_flow_id=res.flow_id or self.pa_flow_id,
			reason_code=reason_code,
			reason_text=reason_text,
			comment=comment,
			amount=amount,
			currency=currency,
			payment_date=payment_date,
		)
		result["new_count"] = 1
		result["logs"].append(("info", f"Lifecycle status '{status}' sent for eInvoice {self.name}"))
		eInvoicingLog.create_log(result)
		return lifecycle_status.label(status)

	def _get_file_for_pa(self) -> tuple[bytes, str, str]:
		"""Return (file_bytes, filename, syntax) for PA submission.

		UBL invoices are sent as raw XML (Factur-X embedding is CII-only).
		Otherwise prefers the already-attached FacturX PDF
		(einvoice_embedded_document), falling back to generating it on the fly.
		"""
		if self.get("syntax") == "UBL":
			xml = self.einvoice_xml
			if isinstance(xml, str):
				xml = xml.encode("utf-8")
			if not xml:
				frappe.throw(_("The UBL XML has not been generated for this eInvoice."))
			return xml, f"{self.sales_invoice}.xml", "UBL"

		if self.einvoice_embedded_document:
			file_doc = frappe.get_doc("File", {"file_url": self.einvoice_embedded_document})
			file_path = file_doc.get_full_path()
			with open(file_path, "rb") as f:
				file_content = f.read()
			return file_content, file_doc.file_name or f"{self.sales_invoice}.pdf", "Factur-X"

		# Generate FacturX PDF on the fly
		from etransactions.utils.facturx_pdf import FacturXPDFGenerator
		generator = FacturXPDFGenerator(self.sales_invoice)
		url = generator.attach_to_invoice()
		# Re-read the file that was just attached
		file_doc = frappe.get_last_doc("File", filters={"attached_to_doctype": "Sales Invoice", "attached_to_name": self.sales_invoice})
		file_path = file_doc.get_full_path()
		with open(file_path, "rb") as f:
			file_content = f.read()
		return file_content, file_doc.file_name or f"{self.sales_invoice}.pdf", "Factur-X"

	@classmethod
	def create_from_plateforme_flow(cls, flow, file_content: bytes | None, company: str) -> "eInvoice":
		"""Create an Incoming eInvoice from a flow received from the accredited platform.

		``flow`` is an IncomingFlow dataclass (etransactions.components.superpdp.models).

		``file_content`` may be ``None``: the record is then created from the flow
		metadata alone, in state ``pending``, and :meth:`fetch_content_from_platform`
		downloads and parses the original file afterwards. That way a flow is never
		lost because its content could not be read — it lands in the inbox either
		way, and the poller has one durable record to retry against.

		With the file present, validate() parses it and on_update() generates the
		Supplier Invoice, as before.
		"""
		file_doc = cls._store_flow_file(flow.flow_id, file_content) if file_content else None

		doc = frappe.new_doc("eInvoice")
		doc.einvoice_type = "Incoming"
		doc.company = company
		doc.pa_flow_id = flow.flow_id
		doc.pa_status = "done"
		doc.pa_submitted_at = flow.submitted_at
		doc.pa_updated_at = flow.updated_at or flow.submitted_at
		doc.pa_flow_type = flow.flow_type
		doc.pa_syntax = flow.syntax
		doc.pa_content_state = "fetched" if file_doc else "pending"
		if file_doc:
			doc.einvoice = file_doc.name
			doc.einvoice_embedded_document = file_doc.file_url
		else:
			doc.apply_flow_metadata(flow)
		doc.flags.ignore_permissions = True
		doc.insert()

		if file_doc:
			cls._attach_flow_file(file_doc, doc.name)

		_notify_incoming_einvoice(doc)

		return doc

	@staticmethod
	def _store_flow_file(flow_id: str, file_content: bytes) -> "File":
		"""Save a downloaded flow, naming it after what the bytes actually are."""
		from etransactions.utils.files import detect_flow_extension

		file_doc = frappe.get_doc({
			"doctype": "File",
			"file_name": f"{flow_id}.{detect_flow_extension(file_content)}",
			"content": file_content,
			"is_private": 1,
		})
		file_doc.flags.ignore_permissions = True
		file_doc.insert()
		return file_doc

	@staticmethod
	def _attach_flow_file(file_doc, einvoice: str) -> None:
		file_doc.db_set({
			"attached_to_doctype": "eInvoice",
			"attached_to_name": einvoice,
			"attached_to_field": "einvoice_embedded_document",
		})

	def apply_flow_metadata(self, flow) -> None:
		"""Fill the identifying fields from the platform's own view of the invoice.

		Only what the inbox needs to be readable before the original file arrives:
		number, dates, currency, totals and the counterparty. Everything else — and
		the authoritative version of these very fields — comes from parsing the file
		in :meth:`fetch_content_from_platform`.
		"""
		en_invoice = getattr(flow, "en_invoice", None) or {}
		invoice = en_invoice.get("invoice") or {}
		seller = en_invoice.get("seller") or {}
		buyer = en_invoice.get("buyer") or {}

		self.id = invoice.get("invoice_number") or invoice.get("number")
		self.issue_date = invoice.get("issue_date")
		self.due_date = invoice.get("due_date")
		self.currency = invoice.get("invoice_currency_code") or invoice.get("currency")
		self.seller_name = seller.get("name") or seller.get("trading_name")
		self.seller_tax_id = seller.get("vat_identifier") or seller.get("tax_identifier")
		self.buyer_name = buyer.get("name") or buyer.get("trading_name")

		for field, key in (
			("line_total", "sum_of_invoice_line_net_amount"),
			("tax_basis_total", "invoice_total_amount_without_vat"),
			("tax_total", "invoice_total_vat_amount"),
			("grand_total", "invoice_total_amount_with_vat"),
			("due_payable", "amount_due_for_payment"),
		):
			value = invoice.get(key)
			if value is not None:
				self.set(field, flt(value))

	def fetch_content_from_platform(self) -> None:
		"""Download the original file of an incoming flow, attach it and parse it.

		Runs out of band from the poller (see
		``etransactions.plateforme_agreee.flow.poll_incoming_flows``) so a file that
		cannot be downloaded or parsed leaves a record behind to retry, instead of
		making the whole flow disappear until the next hourly run.
		"""
		from etransactions.plateforme_agreee.session import get_client

		if self.einvoice_type != "Incoming" or not self.pa_flow_id:
			return

		# A savepoint, not a full rollback: a half-written attempt is undone without
		# touching whatever the caller (the poller, or the retry job) already did.
		save_point = "einvoice_content"
		frappe.db.savepoint(save_point)
		try:
			client = get_client(self.company, transaction_type="purchases")
			file_content = client.download_flow(self.pa_flow_id)
			if not file_content:
				raise ValueError(_("The platform returned an empty file."))

			file_doc = self._store_flow_file(self.pa_flow_id, file_content)
			self.einvoice = file_doc.name
			self.einvoice_embedded_document = file_doc.file_url
			self.pa_content_state = "fetched"
			self.pa_content_error = None
			self.flags.ignore_permissions = True
			self.save()
			self._attach_flow_file(file_doc, self.name)
		except Exception as e:
			frappe.db.rollback(save_point=save_point)
			self.reload()
			self.db_set(
				{"pa_content_state": "error", "pa_content_error": str(e)[:500]},
				update_modified=False,
			)
			frappe.log_error(
				title=f"eInvoice content fetch failed ({self.pa_flow_id})",
				message=frappe.get_traceback(),
				reference_doctype="eInvoice",
				reference_name=self.name,
			)
		else:
			frappe.db.release_savepoint(save_point)

	def onload(self):
		if self.docstatus == 0:
			return

	def read_values_from_einvoice(self) -> None:
		if not self.einvoice:
			return

		eInvoiceParser(self).parse_einvoice()

	def guess_company(self):
		if self.company:
			return

		if frappe.db.exists("Company", self.buyer_name):
			self.company = self.buyer_name
		else:
			self.company = get_default_company()

	def guess_uom(self):
		for row in self.items:
			if row.uom:
				continue

			if row.unit_code:
				rec20_3 = get_docnames_for("urn:xoev-de:kosit:codeliste:rec20_3", "UOM", row.unit_code)
				if rec20_3:
					row.uom = rec20_3[0]
				else:
					rec21_3 = get_docnames_for("urn:xoev-de:kosit:codeliste:rec21_3", "UOM", row.unit_code)
					if rec21_3:
						row.uom = rec21_3[0]
			elif row.item:
				stock_uom, purchase_uom = frappe.db.get_value("Item", row.item, ["stock_uom", "purchase_uom"])
				row.uom = purchase_uom or stock_uom


	def guess_po_details(self):
		if not self.purchase_order:
			for pi_row in self.items:
				pi_row.po_detail = None
			return

		purchase_order = frappe.get_doc("Purchase Order", self.purchase_order)
		po_items = [
			frappe._dict(
				name=po_row.name,
				item_code=po_row.item_code,
				unbilled_amount=po_row.amount - po_row.billed_amt,
			)
			for po_row in purchase_order.items
		]
		for pi_row in self.items:
			if pi_row.po_detail and frappe.db.exists(
				"Purchase Order Item", {"name": pi_row.po_detail, "parent": self.purchase_order}
			):
				continue

			for po_row in po_items:
				if po_row.item_code == pi_row.item and po_row.unbilled_amount >= pi_row.total_amount:
					pi_row.po_detail = po_row.name
					po_row.unbilled_amount -= pi_row.total_amount
					break
			else:
				pi_row.po_detail = None

	def add_seller_product_ids_to_items(self):
		if self.einvoice_type == "Incoming":
			return

		for row in self.items:
			try:
				# This is a convenience feature. Failure to update the Item data
				# should not prevent submission of the E Invoice.
				row.add_seller_product_id_to_item(self.supplier)
			except frappe.ValidationError:
				frappe.log_error(
					title="Failed to store Seller Product ID",
					reference_doctype=self.doctype,
					reference_name=self.name,
				)

	def validate_einvoice(self):
		self.validation_errors = ""
		self.validation_warnings = ""

		if not self.profile:
			return

		try:
			xml_string = self.einvoice_xml.decode()
		except Exception:
			msg = _("Cannot create E Invoice.")
			self.validation_errors = msg
			frappe.log_error(msg, reference_doctype=self.doctype, reference_name=self.name)
			return

		try:
			invoice_profile = EInvoiceProfile(self.profile)
			syntax = self.get("syntax") or "CII"
			validation_errors, warnings = get_validation_errors(xml_string, invoice_profile, syntax)

			if invoice_profile == EInvoiceProfile.XRECHNUNG and syntax != "UBL":
				basic_errors, basic_warnings = get_validation_errors(xml_string, EInvoiceProfile.EN16931)
				validation_errors += basic_errors
				warnings += basic_warnings
		except Exception as e:
			# Validation must never block save, but the stored text has to say
			# what actually failed instead of a generic message.
			msg = _("Cannot validate E Invoice schematron: {0}").format(str(e))
			self.validation_errors = msg
			frappe.log_error(
				title="Schematron validation crashed",
				message=frappe.get_traceback(),
				reference_doctype=self.doctype,
				reference_name=self.name,
			)
			return

		if any(validation_errors):
			self.validation_errors += "\n".join(validation_errors)

		if any(warnings):
			self.validation_warnings += "\n".join(warnings)

	def generate_supplier_invoice(self):
		data = IncomingInvoiceDataTransformer(self).get_data()

		doc = frappe.new_doc("Supplier Invoice")
		doc.update(data)
		doc.einvoice = self.name
		doc.insert(ignore_mandatory=True, ignore_links=True)

		self.attach_source_file_to(doc)

		return doc

	def attach_source_file_to(self, supplier_invoice) -> None:
		"""Give the Supplier Invoice its own copy of the received e-invoice file.

		The Supplier Invoice preview reads ``file``, and a copy attached to the Supplier
		Invoice itself is what lets an Accounts User read the private file: File permissions
		are derived from the document the file hangs off, and eInvoice is not readable by
		that role.
		"""
		if not self.einvoice or not frappe.db.exists("File", self.einvoice):
			return

		file_name = copy_file_to_document(self.einvoice, "Supplier Invoice", supplier_invoice.name)
		file_url = frappe.db.get_value("File", file_name, "file_url")

		# db_set because file_url only fetches from file on save, and the document was just inserted
		supplier_invoice.db_set({"file": file_name, "file_url": file_url}, update_modified=False)



def _notify_incoming_einvoice(doc):
	"""Best-effort: raise a bell notification for a legally-received e-invoice.

	Inbound invoices arrive by silent hourly cron; without this, a received
	e-invoice can sit unseen. Never blocks flow ingestion.
	"""
	try:
		from frappe.desk.doctype.notification_log.notification_log import (
			enqueue_create_notification,
		)

		users = frappe.get_all(
			"Has Role",
			filters={"role": "Accounts Manager", "parenttype": "User"},
			pluck="parent",
		)
		users = [
			u
			for u in set(users)
			if u not in ("Administrator", "Guest")
			and frappe.db.get_value("User", u, "enabled")
		]
		if not users:
			return

		sender = doc.seller_name or doc.pa_flow_id or doc.name
		enqueue_create_notification(
			users,
			{
				"type": "Alert",
				"document_type": "eInvoice",
				"document_name": doc.name,
				"subject": _("New e-invoice received from the accredited platform: {0}").format(sender),
			},
		)
	except Exception:
		frappe.log_error(
			title="Incoming e-invoice notification failed",
			message=frappe.get_traceback(),
			reference_doctype="eInvoice",
			reference_name=doc.name,
		)


@frappe.whitelist()
def get_lifecycle_reason_codes(status: str) -> list[str]:
	"""Return the allowed MDT-113 reason codes for a lifecycle status (for the UI)."""
	from etransactions.plateforme_agreee import lifecycle_status
	return lifecycle_status.reason_codes(status)


@frappe.whitelist()
def get_supported_lifecycle_statuses(einvoice: str) -> dict:
	"""The lifecycle statuses that can actually be reported on this eInvoice right now.

	Two filters are applied. What the platform can carry: SuperPDP only accepts statuses
	with a native ``fr:`` code, CDAR platforms (Esalink/AFNOR) carry every status with an
	MDT-105 code. And what the invoice's current state allows, through the very
	predicate the server enforces at send time — so the UI can never offer a button that
	would be rejected, and an already-reported or contradictory status simply disappears.

	The button metadata (label, reason code required, confirmation) is served from here
	too, so the client does not keep a second copy of the status registry.
	"""
	doc = frappe.get_doc("eInvoice", einvoice)
	doc.check_permission("read")

	from etransactions.plateforme_agreee import lifecycle_status
	from etransactions.plateforme_agreee.session import get_platform_for_company
	from etransactions.etransactions.doctype.einvoice_event.einvoice_event import (
		current_lifecycle_state,
	)

	transaction_type = "sales" if doc.einvoice_type == "Outgoing" else "purchases"
	platform = get_platform_for_company(doc.company, transaction_type=transaction_type)
	if platform and platform.platform_type == "SuperPDP":
		carried = {k for k, v in lifecycle_status.STATUSES.items() if v.get("superpdp")}
	else:
		carried = {k for k, v in lifecycle_status.STATUSES.items() if v.get("mdt105")}

	# We only ever report our own side: the buyer's statuses on an invoice we received,
	# the seller's on one we issued.
	side = "sale" if doc.einvoice_type == "Outgoing" else "purchase"
	state = current_lifecycle_state(einvoice)
	offered = [k for k in lifecycle_status.manual_statuses(side) if k in carried]

	statuses = [
		{
			"status": key,
			"label": lifecycle_status.label(key),
			"reason": lifecycle_status.reason_required(key),
			"confirm": lifecycle_status.confirm_required(key),
			"confirm_message": lifecycle_status.confirm_message(key),
			"decoration": lifecycle_status.STATUSES[key].get("decoration"),
		}
		for key in offered
		if not lifecycle_status.transition_error(state, key)
	]

	# Nothing left to report: surface the reason, so the user sees an explanation
	# instead of an empty action menu.
	blocked_reason = None
	if not statuses:
		blocked_reason = next(
			(err for k in offered if (err := lifecycle_status.transition_error(state, k))), None
		)

	def _axis(axis: str) -> dict:
		current = state[axis]
		return {
			"status": current,
			"label": lifecycle_status.label(current) if current else None,
			"decoration": (lifecycle_status.STATUSES.get(current) or {}).get("decoration"),
			"reported_at": state[f"{axis}_at"],
		}

	return {
		"side": side,
		"statuses": statuses,
		"state": {
			"purchase": _axis("purchase"),
			"sale": _axis("sale"),
			"refused": state["refused"],
			"cancelled": state["cancelled"],
		},
		"blocked_reason": blocked_reason,
	}


def einvoice_for_transaction(doctype: str, name: str) -> str | None:
	"""Name of the eInvoice behind a Sales / Purchase Invoice, whatever its origin.

	The single resolver both the lifecycle panel and the readiness panel go through, so
	the two cannot disagree about which e-invoice a transaction belongs to.
	"""
	if doctype == "Sales Invoice":
		return frappe.db.get_value(
			"eInvoice", {"sales_invoice": name, "einvoice_type": "Outgoing"}, "name"
		)
	if doctype == "Purchase Invoice":
		from etransactions.plateforme_agreee.auto_status import einvoice_for_purchase_invoice

		return einvoice_for_purchase_invoice(name)
	return None


@frappe.whitelist()
def get_transaction_einvoice(doctype: str, name: str) -> dict | None:
	"""Resolve the eInvoice (and its PA status) behind a Sales / Purchase Invoice.

	Lets the transaction forms surface the lifecycle without leaving the document.
	Returns ``None`` when the transaction has no e-invoice at all — an e-invoice that
	never reached a platform still has a lifecycle worth showing, so ``pa_flow_id`` is
	reported rather than required (the client hides the PA ribbon without one).
	"""
	frappe.get_doc(doctype, name).check_permission("read")

	einvoice = einvoice_for_transaction(doctype, name)
	if not einvoice:
		return None

	data = frappe.db.get_value(
		"eInvoice",
		einvoice,
		["name", "pa_status", "pa_flow_id", "pa_content_state", "einvoice_type"],
		as_dict=True,
	)
	if not data:
		return None
	data["side"] = "sale" if data.einvoice_type == "Outgoing" else "purchase"
	return data


@frappe.whitelist()
def report_lifecycle_status(einvoice: str, status: str, **kwargs):
	"""Thin wrapper so transaction forms can drive lifecycle on the linked eInvoice."""
	doc = frappe.get_doc("eInvoice", einvoice)
	doc.check_permission("write")
	return doc.submit_lifecycle_status(status, **kwargs)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def po_item_query(doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict, as_dict: bool | None = False):
	item_code = filters.pop("item_code", None)
	purchase_order = filters.pop("parent", None)

	if not purchase_order:
		return []

	purchase_order = frappe.get_cached_doc("Purchase Order", purchase_order)
	purchase_order.check_permission("read")

	results = [
		[
			row.name,
			_("Row {0}").format(row.idx),
			row.item_code,
			row.description[:100] + "..." if len(row.description) > 40 else row.description,
			row.get_formatted("qty") + " " + row.uom,
			row.get_formatted("net_rate") + " / " + row.uom,
		]
		for row in purchase_order.items
		if not item_code or row.item_code == item_code
	]

	if not txt:
		return results

	return [row for row in results if txt in ", ".join(row)]


@frappe.whitelist()
def get_po_item_details(po_detail: str):
	purchase_order_name = frappe.db.get_value("Purchase Order Item", po_detail, "parent")
	purchase_order = frappe.get_cached_doc("Purchase Order", purchase_order_name)
	if not purchase_order.has_permission("read"):
		return {}

	row = purchase_order.getone("items", {"name": po_detail})
	return {
		"item_code": row.item_code,
		"uom": row.uom,
	}



class IncomingInvoiceDataTransformer(InvoiceEntityResolverMixin):
	def __init__(self, invoice_doc):
		self.invoice_doc = invoice_doc

	def get_data(self):
		data = {
			"company": self.get_company(),
			"supplier": self.get_supplier(),
			"match_confidence": getattr(self, "_match_confidence", None) or "low",
			"supplier_name": self.invoice_doc.seller_name,
			"bill_no": self.invoice_doc.id,
			"bill_date": self.invoice_doc.issue_date,
			"due_date": self.invoice_doc.due_date,
			"currency": self.invoice_doc.currency,
			"supplier_net_amount": self.invoice_doc.line_total,
			"supplier_tax_amount": self.invoice_doc.tax_total,
			"supplier_grand_total": self.invoice_doc.grand_total,
			"vendor_address": self.get_seller_address(),
			"tax_id": self.invoice_doc.seller_tax_id,
			"vendor_iban": self.invoice_doc.payee_iban,
			"einvoice": self.invoice_doc.name,
			"ocr_basket": self.invoice_doc.supplier_invoices_basket,
			"items": []
		}

		for item in self.invoice_doc.items:
			data["items"].append({
				"supplier_description": item.product_name,
				"description": item.product_description,
				"supplier_item_code": item.seller_product_id,
				"item_code": item.item,
				"qty": item.billed_quantity,
				"rate": item.net_rate,
				"amount": item.total_amount,
			})

		return data

	def get_seller_address(self):
		address_parts = [
			self.invoice_doc.seller_address_line_1,
			self.invoice_doc.seller_address_line_2,
			self.invoice_doc.seller_postcode,
			self.invoice_doc.seller_city,
			self.invoice_doc.seller_country
		]
		return ", ".join([p for p in address_parts if p])

	def get_buyer_address(self):
		address_parts = [
			self.invoice_doc.buyer_address_line_1,
			self.invoice_doc.buyer_address_line_2,
			self.invoice_doc.buyer_postcode,
			self.invoice_doc.buyer_city,
			self.invoice_doc.buyer_country
		]
		return ", ".join([p for p in address_parts if p])

	def get_supplier(self):
		return self.resolve_supplier(
			seller_name=self.invoice_doc.seller_name,
			tax_id=self.invoice_doc.seller_tax_id,
			iban=self.invoice_doc.payee_iban,
		)

	def get_company(self):
		if self.invoice_doc.company:
			return self.invoice_doc.company
			
		return self.resolve_company(
			receiver_name=self.invoice_doc.buyer_name,
			receiver_address=self.get_buyer_address()
		)