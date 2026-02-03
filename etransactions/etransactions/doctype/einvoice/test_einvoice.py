# Copyright (c) 2026, ALYF GmbH, Dokos SAS and Contributors
# See license.txt

# import frappe
from frappe.tests import IntegrationTestCase

IGNORE_TEST_RECORD_DEPENDENCIES = ["Company", "Item", "Currency", "Purchase Order", "Sales Invoice", "Supplier", "Address"]

class TesteInvoice(IntegrationTestCase):
	pass
