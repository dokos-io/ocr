# Copyright (c) 2026, Dokos SAS and Contributors
# For license information, please see license.txt

from frappe.tests import UnitTestCase

from etransactions.schematron import PROFILE_TO_XSL, extract_failed_asserts, get_validation_errors
from etransactions.utils import EInvoiceProfile

SVRL = b"""<svrl:schematron-output xmlns:svrl="http://purl.oclc.org/dsdl/svrl">
	<svrl:failed-assert flag="fatal" location="/Invoice"><svrl:text>blocking rule</svrl:text></svrl:failed-assert>
	<svrl:failed-assert flag="warning" location="/Invoice"><svrl:text>advisory rule</svrl:text></svrl:failed-assert>
	<svrl:failed-assert location="/Invoice"><svrl:text>unflagged rule</svrl:text></svrl:failed-assert>
	<svrl:successful-report location="/Invoice"><svrl:text>reported rule</svrl:text></svrl:successful-report>
</svrl:schematron-output>"""


class TestSchematronProfiles(UnitTestCase):
	"""Every profile must resolve to a stylesheet or an explicit no-local-schematron
	sentinel — never a KeyError silently swallowed by the validation guards."""

	def test_every_profile_has_a_mapping(self):
		for profile in EInvoiceProfile:
			self.assertIn(profile, PROFILE_TO_XSL, f"{profile} missing from PROFILE_TO_XSL")

	def test_minimum_and_basic_wl_yield_a_warning_not_a_crash(self):
		for profile in (EInvoiceProfile.MINIMUM, EInvoiceProfile.BASIC_WL):
			errors, warnings = get_validation_errors("<CrossIndustryInvoice/>", profile)
			self.assertEqual(errors, [])
			self.assertEqual(len(warnings), 1)
			self.assertIn("accredited platform", warnings[0])

	def test_unknown_profile_raises_explicitly(self):
		with self.assertRaises(ValueError):
			get_validation_errors("<x/>", "not-a-profile")


class TestSvrlSeverityRouting(UnitTestCase):
	"""Only fatal assertions may block: validation_errors stops Factur-X PDF
	generation, so advisory rules (whole stylesheets are shipped flag="warning",
	e.g. the FNFE BR-FR-Flux2 pre-flight) must land in warnings."""

	def test_flag_decides_the_bucket(self):
		errors, warnings = extract_failed_asserts(SVRL)
		self.assertEqual(errors, ["blocking rule [/Invoice]", "unflagged rule [/Invoice]"])
		self.assertEqual(warnings, ["advisory rule [/Invoice]", "reported rule"])
