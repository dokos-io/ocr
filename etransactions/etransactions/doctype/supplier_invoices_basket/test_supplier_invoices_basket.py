# Copyright (c) 2026, Dokos SAS and Contributors
# For license information, please see license.txt

import os
from unittest.mock import patch

import frappe

from etransactions.etransactions.doctype.supplier_invoices_basket.supplier_invoices_basket import (
	make_basket_from_communication,
)
from etransactions.tests.utils import eTransactionsTestSuite, minimal_pdf_content


# On IntegrationTestCase, the doctype test records and all
# link-field test record dependencies are recursively loaded
# Use these module variables to add/remove to/from that list
EXTRA_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]
IGNORE_TEST_RECORD_DEPENDENCIES = []  # eg. ["User"]



class IntegrationTestSupplierInvoicesBasket(eTransactionsTestSuite):
	"""
	Integration tests for SupplierInvoicesBasket.
	Use this class for testing interactions between multiple components.
	"""

	def setUp(self):
		super().setUp()
		frappe.db.set_default("company", "_Test Company")

	# ------------------------------------------------------------------
	# Fixtures
	# ------------------------------------------------------------------
	def _facturx_pdf(self) -> bytes:
		# get_app_path scrubs its arguments, so the file name is joined separately
		folder_path = frappe.get_app_path("etransactions", "tests", "invoices", "1.basic_wl")
		with open(
			os.path.join(folder_path, "Facture_F20220023-LE_FOURNISSEUR-POUR-LE_CLIENT_BASIC_WL.pdf"),
			"rb",
		) as f:
			return f.read()

	def _communication(self, subject: str = "Facture de juin") -> str:
		communication = frappe.new_doc("Communication")
		communication.update(
			{
				"communication_type": "Communication",
				"communication_medium": "Email",
				"sent_or_received": "Received",
				"subject": subject,
				"sender": "fournisseur@example.com",
				"content": "Veuillez trouver notre facture en pièce jointe.",
			}
		)
		communication.insert(ignore_permissions=True)
		return communication.name

	def _attach_invoice(self, communication: str) -> str:
		file = frappe.new_doc("File")
		file.update(
			{
				"file_name": f"facture-{frappe.generate_hash(length=6)}.pdf",
				"attached_to_doctype": "Communication",
				"attached_to_name": communication,
				"is_private": 1,
				"content": self._facturx_pdf(),
			}
		)
		file.insert()
		return file.name

	def _basket_with_plain_pdf(self):
		basket = frappe.new_doc("Supplier Invoices Basket")
		basket.insert()
		file = frappe.new_doc("File")
		file.update(
			{
				"file_name": f"proforma-{frappe.generate_hash(length=6)}.pdf",
				"attached_to_doctype": "Supplier Invoices Basket",
				"attached_to_name": basket.name,
				"is_private": 1,
				"content": minimal_pdf_content(),
			}
		)
		file.insert()
		return basket, file.name

	def _route_to_ocr(self, basket):
		# A plain PDF is not an eInvoice, so it goes to OCR; keep the analysis
		# job from calling the real OCR service.
		with (
			patch(
				"etransactions.etransactions.doctype.supplier_invoices_basket.supplier_invoices_basket.is_ocr_service_configured",
				return_value=True,
			),
			patch("frappe.enqueue_doc"),
		):
			frappe.get_doc("Supplier Invoices Basket", basket.name).route_invoices()

	# ------------------------------------------------------------------
	# route_invoices
	# ------------------------------------------------------------------
	def test_routing_twice_creates_one_ocr_request_per_file(self):
		"""A double click on "Create purchase invoices" sent the same PDF to OCR twice."""
		basket, file_name = self._basket_with_plain_pdf()

		self._route_to_ocr(basket)
		self._route_to_ocr(basket)

		self.assertEqual(
			frappe.db.count("OCR Request", {"ocr_basket": basket.name, "file": file_name}), 1
		)
		self.assertEqual(frappe.db.get_value("Supplier Invoices Basket", basket.name, "status"), "Completed")

	def test_rerouting_a_reopened_basket_skips_files_already_sent_to_ocr(self):
		basket, file_name = self._basket_with_plain_pdf()
		self._route_to_ocr(basket)

		frappe.db.set_value("Supplier Invoices Basket", basket.name, "status", "Not Started")
		self._route_to_ocr(basket)

		self.assertEqual(
			frappe.db.count("OCR Request", {"ocr_basket": basket.name, "file": file_name}), 1
		)

	# ------------------------------------------------------------------
	# make_basket_from_communication
	# ------------------------------------------------------------------
	def test_basket_from_communication_routes_its_attachments(self):
		"""The Communication button creates a basket, links the email and routes its files.

		Guards two past regressions: the whitelisted method was called under a
		misspelt module path (`supplier_invoice_basket`), and it ended on a
		`run_method("create_requests")` that silently did nothing, leaving the
		basket empty at "Not Started".
		"""
		communication = self._communication()
		file_name = self._attach_invoice(communication)

		basket = make_basket_from_communication(communication=communication)

		self.assertTrue(frappe.db.exists("Supplier Invoices Basket", basket.name))
		self.assertEqual(basket.subject, "Facture de juin")
		self.assertEqual(basket.sender, "fournisseur@example.com")

		# the email is now linked to the basket
		linked = frappe.db.get_value(
			"Communication", communication, ["reference_doctype", "reference_name", "status"], as_dict=True
		)
		self.assertEqual(linked.reference_doctype, "Supplier Invoices Basket")
		self.assertEqual(linked.reference_name, basket.name)
		self.assertEqual(linked.status, "Linked")

		# the attachment was actually routed: a Factur-X PDF goes down the eInvoice
		# branch, so no OCR service is needed
		einvoice = frappe.db.get_value(
			"eInvoice", {"supplier_invoices_basket": basket.name}, ["name", "einvoice"], as_dict=True
		)
		self.assertIsNotNone(einvoice, "the Factur-X attachment should have produced an eInvoice")
		self.assertEqual(einvoice.einvoice, file_name)

		self.assertEqual(
			frappe.db.get_value("Supplier Invoices Basket", basket.name, "status"), "Completed"
		)

	def test_basket_from_communication_without_attachment_is_closed(self):
		communication = self._communication("Simple question")

		basket = make_basket_from_communication(communication=communication)

		basket_state = frappe.db.get_value(
			"Supplier Invoices Basket", basket.name, ["status", "error"], as_dict=True
		)
		self.assertEqual(basket_state.status, "Closed")
		self.assertTrue(basket_state.error)

	def test_basket_from_communication_requires_permissions(self):
		communication = self._communication()

		frappe.set_user("Guest")
		try:
			self.assertRaises(
				frappe.PermissionError,
				make_basket_from_communication,
				communication=communication,
			)
		finally:
			frappe.set_user("Administrator")
