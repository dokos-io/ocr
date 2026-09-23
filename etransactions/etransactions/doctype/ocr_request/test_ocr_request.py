# Copyright (c) 2023, Dokos SAS and Contributors
# For license information, please see license.txt

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import frappe
import httpx
from frappe.tests.utils import FrappeTestCase
from frappe.utils.password import set_encrypted_password
from mistralai.client.errors import SDKError

from etransactions.tests.utils import minimal_pdf_content
from etransactions.utils import parse_currency_symbol

IGNORE_TEST_RECORD_DEPENDENCIES = []


def _supplier_group():
	name = frappe.db.get_value("Supplier Group", {"is_group": 0})
	if name:
		return name
	root = frappe.db.get_value("Supplier Group", {"is_group": 1})
	group = frappe.new_doc("Supplier Group")
	group.supplier_group_name = "_Test OCR Currency Group"
	group.parent_supplier_group = root
	group.is_group = 0
	group.insert(ignore_if_duplicate=True)
	return group.name


def _make_supplier(supplier_name, default_currency=None):
	supplier = frappe.new_doc("Supplier")
	supplier.supplier_name = supplier_name
	supplier.supplier_group = _supplier_group()
	if default_currency:
		supplier.default_currency = default_currency
	supplier.insert(ignore_if_duplicate=True)
	return supplier


class TestParseCurrencySymbol(FrappeTestCase):
	def test_symbols(self):
		self.assertEqual(parse_currency_symbol("$ 54.09"), "USD")
		self.assertEqual(parse_currency_symbol("a 1.190,00 €"), "EUR")
		self.assertEqual(parse_currency_symbol("£12"), "GBP")

	def test_iso_code_wins(self):
		self.assertEqual(parse_currency_symbol("EUR 100,00"), "EUR")
		self.assertEqual(parse_currency_symbol("USD 75.02"), "USD")

	def test_no_currency(self):
		self.assertIsNone(parse_currency_symbol("100,00"))
		self.assertIsNone(parse_currency_symbol(""))
		self.assertIsNone(parse_currency_symbol(None))


class TestOCRRequestCurrency(FrappeTestCase):
	def setUp(self):
		self.suffix = frappe.generate_hash(length=6).upper()
		self.request = frappe.new_doc("OCR Request")

	def tearDown(self):
		frappe.db.rollback()

	def test_supplier_default_currency_is_used(self):
		# A non-company-currency supplier must drive the invoice currency.
		sup = _make_supplier(f"USD Supplier {self.suffix}", default_currency="USD")

		currency = self.request.resolve_currency(sup.name, {"TOTAL": "$ 54.09"})

		self.assertEqual(currency, "USD")

	def test_supplier_default_wins_over_ocr_symbol(self):
		sup = _make_supplier(f"GBP Supplier {self.suffix}", default_currency="GBP")

		# Even if the OCR amount carries a different symbol, the configured supplier
		# currency takes precedence.
		currency = self.request.resolve_currency(sup.name, {"TOTAL": "$ 10.00"})

		self.assertEqual(currency, "GBP")

	def test_falls_back_to_ocr_symbol(self):
		# Supplier without a configured currency: detect it from the OCR amounts.
		sup = _make_supplier(f"No Currency Supplier {self.suffix}")
		frappe.db.set_value("Supplier", sup.name, "default_currency", None)

		currency = self.request.resolve_currency(sup.name, {"TOTAL": "$ 54.09"})

		self.assertEqual(currency, "USD")

	def test_returns_none_when_unresolvable(self):
		# No supplier and no currency signal -> None, so the Supplier Invoice
		# fetch_if_empty fallback fills the company default currency.
		currency = self.request.resolve_currency(None, {"TOTAL": "100,00"})

		self.assertIsNone(currency)


class TestMistralOCRAnalysis(FrappeTestCase):
	def setUp(self):
		frappe.db.set_single_value("eTransactions Settings", "ocr_service", "Mistral OCR")
		set_encrypted_password("eTransactions Settings", "eTransactions Settings", "test-key", "mistral_api_key")

		file = frappe.new_doc("File")
		file.update(
			{
				"file_name": f"proforma-{frappe.generate_hash(length=6)}.pdf",
				"is_private": 1,
				"content": minimal_pdf_content(),
			}
		)
		file.insert()
		self.file = file

		self.client = MagicMock()
		patcher = patch(
			"etransactions.etransactions.doctype.ocr_request.mistral_ocr.Mistral",
			return_value=self.client,
		)
		patcher.start()
		self.addCleanup(patcher.stop)

	def tearDown(self):
		frappe.db.rollback()

	def _request(self):
		request = frappe.new_doc("OCR Request")
		request.file = self.file.name
		request.filename = self.file.file_name
		# Analysis is run explicitly below, not by the after_insert job
		with patch("frappe.enqueue_doc"):
			request.insert()
		return request

	def test_file_is_sent_inline_with_the_annotation_prompt(self):
		self.client.ocr.process.return_value = SimpleNamespace(
			document_annotation=frappe.as_json({"INVOICE_RECEIPT_ID": "PF-7492031", "children": []})
		)
		request = self._request()

		request.make_analysis()

		self.client.files.upload.assert_not_called()
		self.client.files.get_signed_url.assert_not_called()
		kwargs = self.client.ocr.process.call_args.kwargs
		self.assertEqual(kwargs["model"], "mistral-ocr-latest")
		self.assertTrue(kwargs["document"]["document_url"].startswith("data:application/pdf;base64,"))
		self.assertTrue(kwargs["document_annotation_prompt"])
		self.assertIn("document_annotation_format", kwargs)
		self.assertNotIn("include_image_base64", kwargs)

		request.reload()
		self.assertFalse(request.job)
		self.assertEqual(frappe.parse_json(request.analysis)["INVOICE_RECEIPT_ID"], "PF-7492031")
		request.set_status()
		self.assertEqual(request.status, "Analysis Completed")

	def test_purchase_invoice_request_creates_its_supplier_invoice_without_a_job(self):
		"""The supplier invoice used to be created only once a Mistral file id was stored in `job`."""
		self.client.ocr.process.return_value = SimpleNamespace(
			document_annotation=frappe.as_json(
				{"INVOICE_RECEIPT_ID": "PF-7492031", "TOTAL": "120,00", "SUBTOTAL": "100,00", "children": []}
			)
		)
		request = self._request()
		request.db_set("transaction_type", "Purchase Invoice")

		request.make_analysis()

		self.assertTrue(frappe.db.exists("Supplier Invoice", {"ocr_request": request.name}))

	def test_rate_limit_error_is_stored_on_the_request(self):
		body = '{"object":"error","message":"Rate limit exceeded","type":"rate_limited","code":"1300"}'
		self.client.ocr.process.side_effect = SDKError(
			"API error occurred",
			httpx.Response(
				429,
				text=body,
				headers={"content-type": "application/json"},
				request=httpx.Request("POST", "https://api.mistral.ai/v1/ocr"),
			),
		)
		request = self._request()

		request.make_analysis()

		# set_and_return_error rolls back first (the uncommitted test request with it),
		# so check the document it updated
		self.assertEqual(request.status, "Error")
		self.assertIn("429", request.error)
		self.assertIn("Rate limit exceeded", request.error)
