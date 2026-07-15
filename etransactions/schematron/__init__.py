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
	# EN16931 and EXTENDED are the FNFE Schematron package v1.4.0 (XP Z12-012
	# V1.4.0) builds; EXTENDED is Factur-X 1.09.2.
	EInvoiceProfile.EN16931: "EN16931-CII-validation.xslt",
	EInvoiceProfile.EXTENDED: "Factur-X_1.09.2_EXTENDED.xslt",
	EInvoiceProfile.XRECHNUNG: "XRechnung-CII-validation.xsl",
	# CTC-FR now has its own dedicated FNFE schematron (v1.4.0), which natively
	# accepts the cpro.gouv.fr extended-ctc-fr guideline — no guideline swap needed.
	EInvoiceProfile.CTC_FR: "EXTENDED-CTC-FR-CII.xslt",
}


# UBL 2.1 documents are validated against the EN16931 core rules plus the
# Peppol BIS 3.0 CIUS (the builder always emits the BIS CustomizationID).
# EN16931-UBL is the FNFE Schematron package v1.4.0 build; Peppol is the
# compiled OpenPeppol peppol-bis-invoice-3 XSLT (phax/phive-rules).
UBL_XSL = ["EN16931-UBL-validation.xslt", "PEPPOL-EN16931-UBL.xslt"]

# French CTC business-rule pre-flight (FNFE BR-FR-Flux2, v1.4.0), run in the
# non-blocking "WARNING" build: failed rules surface as successful-reports, which
# extract_failed_asserts() routes to warnings (never validation_errors), so they
# never block Factur-X PDF generation. Applied only to the French Extended /
# CTC-FR CII profiles — never to international Peppol UBL, which does not carry
# the French reform rules (and which the generator never emits for these profiles).
FRENCH_CTC_CII_PROFILES = (EInvoiceProfile.EXTENDED, EInvoiceProfile.CTC_FR)
FRENCH_CTC_CII_WARNING = "BR-FR-Flux2-Schematron-CII_WARNING.xslt"


def get_stylesheets(profile: EInvoiceProfile, syntax: str = "CII") -> list[str] | None:
	"""Stylesheets to run for a document, or None when no local schematron applies."""
	if syntax == "UBL":
		return list(UBL_XSL)
	if profile not in PROFILE_TO_XSL:
		raise ValueError(f"No schematron mapping for e-invoice profile {profile!r}")
	stylesheet = PROFILE_TO_XSL[profile]
	if stylesheet is None:
		return None
	stylesheets = [stylesheet]
	# Append the non-blocking French CTC pre-flight for the French CII profiles.
	if profile in FRENCH_CTC_CII_PROFILES:
		stylesheets.append(FRENCH_CTC_CII_WARNING)
	return stylesheets


def get_validation_errors(xml_string: str, profile: EInvoiceProfile, syntax: str = "CII"):
	stylesheets = get_stylesheets(profile, syntax)
	if stylesheets is None:
		return [], [
			_(
				"The {0} profile has no local schematron; the accredited platform validates it on submit."
			).format(profile.value)
		]

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
