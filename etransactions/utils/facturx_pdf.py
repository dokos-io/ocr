# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

from facturx import generate_from_binary
import frappe
from frappe import _

from etransactions.utils import EInvoiceProfile


_PROFILE_TO_FACTURX_LEVEL: dict[EInvoiceProfile, str] = {
	EInvoiceProfile.MINIMUM: "minimum",
	EInvoiceProfile.BASIC_WL: "basicwl",
	EInvoiceProfile.BASIC: "basic",
	EInvoiceProfile.EN16931: "en16931",
	EInvoiceProfile.XRECHNUNG: "en16931",  # XRechnung is EN16931-compliant; guideline URI carried in XML
	EInvoiceProfile.EXTENDED: "extended",
}


class FacturXPDFGenerator:
	"""Embed a CII XML eInvoice into the Sales Invoice PDF to produce a FacturX hybrid document."""

	def __init__(self, sales_invoice_name: str):
		self.sales_invoice_name = sales_invoice_name
		self._einvoice_name: str | None = None

	@property
	def einvoice_name(self) -> str | None:
		if self._einvoice_name is None:
			self._einvoice_name = frappe.db.get_value(
				"eInvoice", {"sales_invoice": self.sales_invoice_name}, "name"
			)
		return self._einvoice_name

	def generate(self) -> bytes:
		"""Return the FacturX PDF as bytes."""
		xml_bytes = self._get_xml_bytes()
		pdf_bytes = self._get_invoice_pdf_bytes()
		level = self._get_facturx_level()
		return generate_from_binary(
			pdf_bytes,
			xml_bytes,
			flavor="factur-x",
			level=level,
			check_xsd=False,  # Schematron validation already ran during eInvoice save
		)

	def attach_to_invoice(self) -> str:
		"""Generate the FacturX PDF and attach it to the Sales Invoice. Returns the file URL."""
		pdf_content = self.generate()
		file_name = f"{self.sales_invoice_name}.pdf"

		existing = frappe.db.get_value(
			"File",
			{
				"file_name": file_name,
				"attached_to_doctype": "Sales Invoice",
				"attached_to_name": self.sales_invoice_name,
			},
		)
		if existing:
			frappe.delete_doc("File", existing, force=True)

		file_doc = frappe.get_doc({
			"doctype": "File",
			"file_name": file_name,
			"attached_to_doctype": "Sales Invoice",
			"attached_to_name": self.sales_invoice_name,
			"content": pdf_content,
			"is_private": 0,
		})
		file_doc.insert(ignore_permissions=True)
		return file_doc.file_url

	def get_attachment_url(self) -> str | None:
		"""Return the URL of the existing FacturX PDF attachment, or None if not yet generated."""
		file_name = f"{self.sales_invoice_name}.pdf"
		return frappe.db.get_value(
			"File",
			{
				"file_name": file_name,
				"attached_to_doctype": "Sales Invoice",
				"attached_to_name": self.sales_invoice_name,
			},
			"file_url",
		)

	def _get_xml_bytes(self) -> bytes:
		if not self.einvoice_name:
			frappe.throw(
				_("No eInvoice found for Sales Invoice {0}. Save the Sales Invoice with an eTransaction Profile first.").format(
					self.sales_invoice_name
				)
			)

		einvoice_xml, validation_errors = frappe.db.get_value(
			"eInvoice", self.einvoice_name, ["einvoice_xml", "validation_errors"]
		)

		if validation_errors:
			frappe.throw(
				_("The eInvoice {0} has validation errors and cannot be embedded in the PDF:\n{1}").format(
					self.einvoice_name, validation_errors
				)
			)

		if not einvoice_xml:
			frappe.throw(
				_("eInvoice {0} has no XML content. Save the Sales Invoice to regenerate it.").format(
					self.einvoice_name
				)
			)

		return einvoice_xml.encode() if isinstance(einvoice_xml, str) else bytes(einvoice_xml)

	def _get_invoice_pdf_bytes(self) -> bytes:
		return frappe.get_print(
			doctype="Sales Invoice",
			name=self.sales_invoice_name,
			as_pdf=True,
		)

	def _get_facturx_level(self) -> str:
		etransaction_profile = frappe.db.get_value(
			"Sales Invoice", self.sales_invoice_name, "etransaction_profile"
		)
		try:
			profile = EInvoiceProfile(etransaction_profile)
			return _PROFILE_TO_FACTURX_LEVEL.get(profile, "en16931")
		except ValueError:
			return "en16931"
