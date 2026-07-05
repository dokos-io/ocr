# Copyright (c) 2026, Dokos SAS and Contributors
# For license information, please see license.txt

from frappe.tests import UnitTestCase

from etransactions.schematron import PROFILE_TO_XSL, get_validation_errors
from etransactions.utils import EInvoiceProfile


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
