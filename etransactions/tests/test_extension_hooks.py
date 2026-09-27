# Copyright (c) 2026, Dokos SAS and Contributors
# For license information, please see license.txt

from unittest.mock import patch

import frappe
from frappe.tests import UnitTestCase

from etransactions.etransactions.doctype.einvoice.einvoice import IncomingInvoiceDataTransformer
from etransactions.etransactions.doctype.einvoice.generator import EInvoiceMapper
from etransactions.utils import hooks


def registered(methods: dict):
	"""Patch frappe hooks so ``methods`` ({hook: [callables]}) are the registered ones."""
	functions = {f"app.{hook}.{index}": fn for hook, fns in methods.items() for index, fn in enumerate(fns)}
	return (
		patch.object(
			hooks.frappe,
			"get_hooks",
			side_effect=lambda name: [path for path in functions if path.startswith(f"app.{name}.")],
		),
		patch.object(hooks.frappe, "get_attr", side_effect=functions.__getitem__),
	)


class TestHookHelpers(UnitTestCase):
	def test_the_first_non_empty_answer_wins(self):
		get_hooks, get_attr = registered(
			{"h": [lambda doc: None, lambda doc: "123456789_A", lambda doc: "other"]}
		)
		with get_hooks, get_attr:
			self.assertEqual(hooks.first_hook_result("h", object()), "123456789_A")
			self.assertIsNone(hooks.first_hook_result("unknown", object()))

	def test_values_are_merged_in_order(self):
		get_hooks, get_attr = registered(
			{"h": [lambda doc: {"a": 1, "b": 1}, lambda doc: None, lambda doc: {"b": 2}]}
		)
		with get_hooks, get_attr:
			self.assertEqual(hooks.merged_hook_values("h", object()), {"a": 1, "b": 2})


class TestSellerElectronicAddressHook(UnitTestCase):
	def mapper(self):
		mapper = EInvoiceMapper.__new__(EInvoiceMapper)
		mapper.einvoice = frappe._dict()
		mapper.sales_invoice = frappe._dict(
			customer="CUST", customer_address=None, contact_email="buyer@example.com"
		)
		mapper.company = frappe._dict(
			etransactions_electronic_address_scheme="SCHEME",
			etransactions_electronic_address="123456789",
			email="cae@example.com",
		)
		mapper.customer = frappe._dict()
		mapper.seller_contact = mapper.buyer_address = None
		return mapper

	def map(self, seller_hooks):
		mapper = self.mapper()
		get_hooks, get_attr = registered({"etransactions_seller_electronic_address": seller_hooks})
		with (
			get_hooks,
			get_attr,
			patch("etransactions.plateforme_agreee.routing.resolve_routing", return_value=None),
			patch.object(frappe.db, "get_value", return_value="0225"),
		):
			mapper.map_electronic_addresses()
		return mapper.einvoice

	def test_a_hook_sends_the_invoice_from_its_own_routing_code(self):
		einvoice = self.map([lambda sales_invoice: "123456789_ATELIER"])
		self.assertEqual(
			(einvoice.seller_electronic_address_scheme, einvoice.seller_electronic_address),
			("0225", "123456789_ATELIER"),
		)

	def test_without_an_answer_the_company_address_is_used(self):
		einvoice = self.map([lambda sales_invoice: None])
		self.assertEqual(
			(einvoice.seller_electronic_address_scheme, einvoice.seller_electronic_address),
			("0225", "123456789"),
		)


class ReceivedInvoice:
	"""A received eInvoice with no items; unset fields read as None."""

	items = ()
	name = "EINV-1"
	buyer_electronic_address = "123456789_ATELIER"

	def __getattr__(self, fieldname):
		return None


class TestIncomingInvoiceValuesHook(UnitTestCase):
	def test_hook_values_are_added_to_the_supplier_invoice(self):
		invoice = ReceivedInvoice()
		transformer = IncomingInvoiceDataTransformer(invoice)
		get_hooks, get_attr = registered(
			{
				"etransactions_incoming_invoice_values": [
					lambda einvoice: {"ruche_enseigne": einvoice.buyer_electronic_address}
				]
			}
		)
		with (
			get_hooks,
			get_attr,
			patch.object(IncomingInvoiceDataTransformer, "get_company", return_value="CAE"),
			patch.object(IncomingInvoiceDataTransformer, "get_supplier", return_value=None),
			patch.object(IncomingInvoiceDataTransformer, "get_seller_address", return_value=""),
			patch("etransactions.etransactions.doctype.einvoice.einvoice.get_item_catalog", return_value=[]),
		):
			data = transformer.get_data()

		self.assertEqual((data["company"], data["ruche_enseigne"]), ("CAE", "123456789_ATELIER"))
