from collections import Counter

import frappe

from etransactions.controllers.entity_resolver import canonical_company, resolve_ocr_buyer_company


def execute():
	"""Give a company to the OCR Supplier Invoices left without one.

	The OCR path matched the buyer on its exact name only. In order, the company comes from:
	the Purchase Invoice made from the Supplier Invoice, the company that older versions stored
	on the OCR Request, and the buyer match on the stored analysis.
	"""
	sources = Counter()
	for invoice in frappe.get_all(
		"Supplier Invoice",
		filters={"company": ("is", "not set"), "ocr_request": ("is", "set")},
		fields=["name", "ocr_request"],
	):
		for source, find_company in (
			("Purchase Invoice", _purchase_invoice_company),
			("OCR Request", _stored_ocr_request_company),
			("analysis", _analysis_company),
		):
			if company := find_company(invoice):
				frappe.db.set_value("Supplier Invoice", invoice.name, "company", company, update_modified=False)
				sources[source] += 1
				break

	for source, count in sources.items():
		print(f"Supplier Invoice: company set from {source} on {count} document(s)")


def _purchase_invoice_company(invoice) -> str | None:
	if not frappe.db.has_column("Purchase Invoice", "supplier_invoice"):
		return None
	return frappe.db.get_value(
		"Purchase Invoice", {"supplier_invoice": invoice.name, "docstatus": ("<", 2)}, "company"
	)


def _stored_ocr_request_company(invoice) -> str | None:
	# The column outlives the field removed from OCR Request
	if not frappe.db.has_column("OCR Request", "company"):
		return None
	value = frappe.db.sql("select company from `tabOCR Request` where name=%s", invoice.ocr_request)
	return canonical_company(value[0][0]) if value else None


def _analysis_company(invoice) -> str | None:
	analysis = frappe.db.get_value("OCR Request", invoice.ocr_request, "analysis")
	return resolve_ocr_buyer_company(frappe.parse_json(analysis) or {}) if analysis else None
