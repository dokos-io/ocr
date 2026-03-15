from pathlib import Path
from typing import TYPE_CHECKING, Literal, NoReturn

import frappe
from frappe import _
from frappe.exceptions import ValidationError
from lxml import etree

from facturx import get_xml_from_pdf

if TYPE_CHECKING:
	from frappe.core.doctype.file.file import File


class UnsupportedEInvoiceDocument(ValidationError):
	pass


class PDFWithoutXMLError(ValidationError):
	pass


# FacturX / CII root namespace (UN/CEFACT Cross-Industry Invoice)
_FACTURX_NAMESPACE = "urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100"

# UBL 2.x root namespaces (OASIS)
_UBL_NAMESPACES = {
	"urn:oasis:names:specification:ubl:schema:xsd:Invoice-2",
	"urn:oasis:names:specification:ubl:schema:xsd:CreditNote-2",
	"urn:oasis:names:specification:ubl:schema:xsd:DebitNote-2",
}

XmlFormat = Literal["facturx", "ubl"]


def _unsupported(msg: str, title: str, exc: type) -> NoReturn:
	frappe.throw(msg=msg, title=title, exc=exc)
	raise exc(msg)  # unreachable; satisfies type checkers


def detect_xml_format(xml_bytes: bytes) -> XmlFormat:
	"""Detect whether XML bytes represent a FacturX/CII or a UBL document.

	Raises :class:`UnsupportedEInvoiceDocument` when the format is unrecognised.
	"""
	try:
		root = etree.fromstring(xml_bytes)
	except etree.XMLSyntaxError as e:
		_unsupported(
			msg=_("The uploaded file does not contain valid XML data: {0}").format(str(e)),
			title=_("Invalid XML"),
			exc=UnsupportedEInvoiceDocument,
		)

	# Clark notation: {namespace}LocalName
	tag = root.tag
	ns = tag.split("}")[0].lstrip("{") if "}" in tag else ""

	if ns == _FACTURX_NAMESPACE or tag.endswith("}CrossIndustryInvoice"):
		return "facturx"

	if ns in _UBL_NAMESPACES or any(tag.endswith(f"}}{t}") for t in ("Invoice", "CreditNote", "DebitNote")):
		return "ubl"

	_unsupported(
		msg=_(
			"The XML document format is not supported. Only FacturX/CII and UBL 2.x invoices are accepted."
		),
		title=_("Unsupported XML format"),
		exc=UnsupportedEInvoiceDocument,
	)


def get_xml_bytes(einvoice: "File") -> tuple[bytes, XmlFormat]:
	"""Reads the XML data from the attached XML or PDF file.

	Returns a ``(xml_bytes, format)`` tuple where *format* is either
	``"facturx"`` or ``"ubl"``.
	"""
	file = Path(einvoice.get_full_path()).resolve()  # TODO: Use get_content ?
	if file.suffix.lower() == ".pdf":
		_xml_filename, xml_bytes = get_xml_from_pdf(file.read_bytes(), check_xsd=False)
		if not xml_bytes:
			_unsupported(
				msg=_(
					"No machine-readable data was found in the PDF file. You can create a regular Purchase Invoice manually instead."
				),
				title=_("Not an E-Invoice"),
				exc=PDFWithoutXMLError,
			)
	elif file.suffix.lower() == ".xml":
		xml_bytes = file.read_bytes()
	else:
		_unsupported(
			msg=_(
				"The format of the uploaded file ({0}) is not supported for E-Invoices. Please upload a valid E-Invoice file or create a regular Purchase Invoice manually instead."
			).format(file.suffix),
			title=_("Unsupported file format"),
			exc=UnsupportedEInvoiceDocument,
		)

	return xml_bytes, detect_xml_format(xml_bytes)
