from pathlib import Path

from frappe import _
from lxml import objectify
from saxonche import PySaxonProcessor

from etransactions.utils import EInvoiceProfile

PROFILE_TO_XSL = {
	# MINIMUM and BASIC WL documents are not full EN16931 invoices: no bundled
	# schematron applies to them, the accredited platform validates on submit.
	EInvoiceProfile.MINIMUM: None,
	EInvoiceProfile.BASIC_WL: None,
	EInvoiceProfile.BASIC: "Factur-X_1.07.2_BASIC.xsl",
	EInvoiceProfile.EN16931: "EN16931-CII-validation-preprocessed.xsl",
	EInvoiceProfile.EXTENDED: "Factur-X_1.07.2_EXTENDED.xsl",
	EInvoiceProfile.XRECHNUNG: "XRechnung-CII-validation.xsl",
	# CTC-FR is Extended-based; validate with the Factur-X EXTENDED schematron.
	# (the cpro.gouv.fr CTC-FR Schematron is not bundled; the PA validates on submit.)
	EInvoiceProfile.CTC_FR: "Factur-X_1.07.2_EXTENDED.xsl",
}


# UBL 2.1 documents are validated against the EN16931 core rules plus the
# Peppol BIS 3.0 CIUS (the builder always emits the BIS CustomizationID).
# Compiled XSLTs from phax/phive-rules (openpeppol 2026.5 ruleset); sources:
# CEN/TC434 schematron (EN16931) and OpenPeppol peppol-bis-invoice-3.
UBL_XSL = ["EN16931-UBL-validation.xslt", "PEPPOL-EN16931-UBL.xslt"]


def get_stylesheets(profile: EInvoiceProfile, syntax: str = "CII") -> list[str] | None:
	"""Stylesheets to run for a document, or None when no local schematron applies."""
	if syntax == "UBL":
		return UBL_XSL
	if profile not in PROFILE_TO_XSL:
		raise ValueError(f"No schematron mapping for e-invoice profile {profile!r}")
	stylesheet = PROFILE_TO_XSL[profile]
	return None if stylesheet is None else [stylesheet]


def get_validation_errors(xml_string: str, profile: EInvoiceProfile, syntax: str = "CII"):
	stylesheets = get_stylesheets(profile, syntax)
	if stylesheets is None:
		return [], [
			_(
				"The {0} profile has no local schematron; the accredited platform validates it on submit."
			).format(profile.value)
		]

	if syntax != "UBL" and profile == EInvoiceProfile.CTC_FR:
		# The bundled schematron is the generic Factur-X EXTENDED one (the
		# cpro.gouv.fr CTC-FR schematron is not bundled). It rejects the French
		# BT-24 guideline URN, so validate with the guideline swapped to the
		# standard extended id: the structural EN16931/Extended rules still apply,
		# while the French-specific rules are enforced by the PA on submit.
		from etransactions.utils import get_guideline

		xml_string = xml_string.replace(
			get_guideline(EInvoiceProfile.CTC_FR),
			get_guideline(EInvoiceProfile.EXTENDED),
		)

	errors: list[str] = []
	warnings: list[str] = []
	for stylesheet in stylesheets:
		sheet_errors, sheet_warnings = get_errors_from_stylesheet(xml_string, stylesheet)
		errors += sheet_errors
		warnings += sheet_warnings
	return errors, warnings


def get_errors_from_stylesheet(xml_string: str, stylesheet: str):
	stylesheet_path = Path(__file__).parent / stylesheet
	report = get_validation_report(xml_string, str(stylesheet_path))
	return extract_failed_asserts(report)


def extract_failed_asserts(xml: bytes) -> tuple[list[str], list[str]]:
	root = objectify.fromstring(xml)
	ns = {"svrl": "http://purl.oclc.org/dsdl/svrl"}
	failed_asserts = root.xpath("//svrl:failed-assert", namespaces=ns)
	warnings = root.xpath("//svrl:successful-report/svrl:text", namespaces=ns)

	def message(node) -> str | None:
		text_nodes = node.xpath("svrl:text", namespaces=ns)
		if not text_nodes or not text_nodes[0].text:
			return None
		text = text_nodes[0].text.strip()
		# The element location pinpoints which field failed — terse rule texts like
		# "Value of 'ram:ID' is not allowed" are unusable without it.
		location = node.get("location")
		return f"{text} [{location}]" if location else text

	errors = [m for node in failed_asserts if (m := message(node))]
	warnings = [warning.text.strip() for warning in warnings if warning.text]
	return errors, warnings


def get_validation_report(xml_string: str, stylesheet_file: str) -> bytes:
	with PySaxonProcessor(license=False) as proc:
		xslt30_processor = proc.new_xslt30_processor()
		input_node = proc.parse_xml(xml_text=xml_string)
		executable = xslt30_processor.compile_stylesheet(stylesheet_file=stylesheet_file)
		report = executable.transform_to_string(xdm_node=input_node)

	return report.encode("utf-8")
