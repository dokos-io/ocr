# Copyright (c) 2026, Dokos SAS and Contributors
# For license information, please see license.txt

# import frappe
from etransactions.tests.utils import eTransactionsTestSuite


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class IntegrationTesteTransactionProfile(eTransactionsTestSuite):
	"""
	Integration tests for eTransactionProfile.
	Use this class for testing interactions between multiple components.
	"""

	pass
