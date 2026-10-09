import frappe

from etransactions.schematron import get_validation_errors
from etransactions.utils import EInvoiceProfile
from etransactions.utils.xml import detect_xml_format


def execute():
	"""Validate again the received eInvoices marked incorrect with no error to show for it.

	The schematron validation crashed on files starting with a byte order mark, and the parser
	then left the invoice marked incorrect without saying why.
	"""
	for einvoice in frappe.get_all(
		"eInvoice",
		filters={
			"einvoice_type": "Incoming",
			"e_invoice_is_correct": 0,
			"validation_errors": ("is", "not set"),
			"einvoice_xml": ("is", "set"),
			"profile": ("is", "set"),
		},
		fields=["name", "profile", "einvoice_xml"],
	):
		xml = einvoice.einvoice_xml
		xml_string = xml.decode("utf-8-sig") if isinstance(xml, bytes) else xml
		try:
			syntax = "UBL" if detect_xml_format(xml_string.lstrip("﻿").encode()) == "ubl" else "CII"
			errors, warnings = get_validation_errors(xml_string, EInvoiceProfile(einvoice.profile), syntax)
		except Exception:
			frappe.log_error(
				title="Schematron validation crashed",
				reference_doctype="eInvoice",
				reference_name=einvoice.name,
			)
			continue

		frappe.db.set_value(
			"eInvoice",
			einvoice.name,
			{
				"e_invoice_is_correct": 0 if any(errors) else 1,
				"validation_errors": "\n".join(errors),
				"validation_warnings": "\n".join(warnings),
			},
			update_modified=False,
		)
