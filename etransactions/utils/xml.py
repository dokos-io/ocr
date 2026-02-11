from pathlib import Path
from typing import TYPE_CHECKING

import frappe
from frappe import _
from frappe.exceptions import ValidationError

from facturx import get_xml_from_pdf

if TYPE_CHECKING:
	from frappe.core.doctype.file.file import File


class UnsupportedEInvoiceDocument(ValidationError):
	pass


class PDFWithoutXMLError(ValidationError):
	pass


def get_xml_bytes(einvoice: File) -> bytes:
	"""Reads the XML data from the attached XML or PDF file."""
	file = Path(einvoice.get_full_path()).resolve() # TODO: Use get_content ?
	if file.suffix.lower() == ".pdf":
		xml_filename, xml_bytes = get_xml_from_pdf(file.read_bytes(), check_xsd=False)
		if not xml_bytes:
			frappe.throw(
				msg=_(
					"No machine-readable data was found in the PDF file. You can create a regular Purchase Invoice manually instead."
				),
				title=_("Not an E-Invoice"),
				exc=PDFWithoutXMLError,
			)
	elif file.suffix.lower() == ".xml":
		xml_bytes = file.read_bytes()
	else:
		frappe.throw(
			msg=_(
				"The format of the uploaded file ({0}) is not supported for E-Invoices. Please upload a valid E-Invoice file or create a regular Purchase Invoice manually instead."
			).format(file.suffix),
			title=_("Unsupported file format"),
			exc=UnsupportedEInvoiceDocument
		)

	return xml_bytes