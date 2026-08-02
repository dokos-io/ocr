# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

"""Shared harness for the Microcks-backed PA integration tests.

These tests drive **real HTTP** from the PA clients to a Microcks mock server
seeded with the OpenAPI specs under ``etransactions/components/mocks``. The
clients are pointed at Microcks by the ``microcks_url`` site_config seam
(:mod:`etransactions.plateforme_agreee._microcks`), so nothing here patches the
transport — the whole stack from ``get_client`` down to ``requests`` runs.

The suite **skips cleanly** when ``microcks_url`` is not configured or the mock
server is unreachable, so it is inert in environments without Microcks (the same
contract conectt uses via ``skip_api_test_cases``). To run it locally:

    ./scripts/microcks-up.sh
    bench --site <site> set-config microcks_url http://localhost:8585
    bench --site <site> run-tests --app etransactions \
        --module etransactions.tests.integration.test_einvoicing_e2e
"""

import frappe
from frappe.tests import IntegrationTestCase

from etransactions.tests.fixtures import clear_platforms, seed_company, seed_item
from etransactions.tests.utils import minimal_pdf_content

try:
	import requests
except ImportError:  # pragma: no cover - requests is a hard dep in practice
	requests = None

COMPANY = "_Test Company"
SELLER_SIREN = "824710776"
# SIREN the mock directory (afnor/esalink specs) answers "active private" for.
BUYER_SIREN = "853322915"
# SIREN the mock directory answers "public" for (B2G).
PUBLIC_SIREN = "130025265"

# Expected mock responses per platform type, keyed by connection mode. The values
# are the flow/invoice ids the mock specs return; tests assert the send round-trips
# them and that status dispatch resolves accepted vs rejected.
PLATFORM_FIXTURES = {
	"Custom": {"ok_flow": "AFNOR-FLOW-OK", "rejected_flow": "AFNOR-FLOW-REJECTED"},
	"SuperPDP": {"ok_flow": "90001", "rejected_flow": "90002"},
	"Esalink": {"ok_flow": "ESA-FLOW-OK", "rejected_flow": "ESA-FLOW-REJECTED"},
}


def microcks_reachable() -> bool:
	"""True when a Microcks server is configured and answering."""
	url = frappe.conf.get("microcks_url")
	if not url or not requests:
		return False
	try:
		resp = requests.get(f"{url.rstrip('/')}/api/keycloak/config", timeout=3)
		return resp.ok
	except Exception:
		return False


class MicrocksTestCase(IntegrationTestCase):
	"""Base for PA integration tests: skips without Microcks, seeds master data."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not microcks_reachable():
			raise cls.skipTest(
				cls,
				"microcks_url is not configured or the Microcks mock server is unreachable; "
				"run scripts/microcks-up.sh and set-config microcks_url to enable these tests.",
			)

	def setUp(self):
		super().setUp()
		# Dummy Esalink partner/api credentials so the seam-redirected clients and the
		# `eTransactions Accredited Platform` validate() gate are satisfied; the base URL
		# is overridden to Microcks, only these conf keys are still read.
		frappe.conf["esalink_api_key"] = "test-api-key"
		frappe.conf["esalink_partner_username"] = "test-partner"
		frappe.conf["esalink_partner_password"] = "test-partner-secret"
		self._clear_platforms()
		self._seed_company()
		self._seed_item()

	def _clear_platforms(self):
		clear_platforms(COMPANY)

	# ------------------------------------------------------------------ masters

	def _seed_company(self):
		self.company_address = seed_company(COMPANY, siren=SELLER_SIREN)

	def _seed_item(self):
		seed_item()

	# ---------------------------------------------------------------- customers

	def make_customer(
		self, name: str, *, entity_type=None, siren=None, country=None, customer_type=None, directory_type=None
	):
		"""Create (idempotently) a Customer classified per the given directory markers.

		``entity_type`` drives classification: ``private`` → B2B, ``public`` → B2G,
		``private_inactive`` → B2C. A foreign ``country`` + ``customer_type='Company'``
		→ B2Bi. An individual (no markers, no country) → B2C. ``directory_type='peppol'``
		routes the eInvoice through UBL (raw XML) instead of Factur-X.
		"""
		if not frappe.db.exists("Customer", name):
			frappe.get_doc(
				{
					"doctype": "Customer",
					"customer_name": name,
					"customer_group": "_Test Customer Group",
					"territory": "_Test Territory",
				}
			).insert(ignore_if_duplicate=True)
		values = {}
		if entity_type is not None:
			values["directory_entity_type"] = entity_type
		if siren is not None:
			values["siren_number"] = siren
		if customer_type is not None:
			values["customer_type"] = customer_type
		if directory_type is not None:
			values["directory_type"] = directory_type
		if values:
			frappe.db.set_value("Customer", name, values, update_modified=False)
		# Every buyer gets a postal address with a country (BR-10/BR-11); default France.
		self._set_customer_address(name, country or "France")
		return name

	def _set_customer_address(self, customer: str, country: str):
		title = f"_Test Addr {customer}"
		if frappe.db.get_value("Address", {"address_title": title}):
			return
		doc = frappe.get_doc(
			{
				"doctype": "Address",
				"address_title": title,
				"address_type": "Billing",
				"address_line1": "10 Rue du Test",
				"city": "Paris" if country == "France" else "Brussels",
				"pincode": "75002",
				"country": country,
				"is_primary_address": 1,
				"links": [{"link_doctype": "Customer", "link_name": customer}],
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert(ignore_if_duplicate=True)

	# ---------------------------------------------------------------- platforms

	def use_platform(self, platform_type: str, *, transaction_type="Both", auto_send=False) -> str:
		"""Make ``platform_type`` the single active platform for the test company.

		Deactivates any other test platforms so ``get_client`` resolves this one, then
		creates/updates the row. Credentials are dummy — the Microcks seam supplies the
		base URL, so a real handshake still runs against the mock.
		"""
		for name in frappe.get_all(
			"eTransactions Accredited Platform", filters={"company": COMPANY}, pluck="name"
		):
			frappe.db.set_value("eTransactions Accredited Platform", name, "is_active", 0, update_modified=False)

		doc = frappe.new_doc("eTransactions Accredited Platform")
		doc.platform_name = f"_Test PA {platform_type}"
		doc.update(
			{
				"platform_type": platform_type,
				"platform_code": platform_type.lower(),
				"company": COMPANY,
				"transaction_type": transaction_type,
				"is_active": 1,
				"auto_send_on_submit": 1 if auto_send else 0,
				"api_base_url": "https://placeholder.invalid",  # overridden by the Microcks seam
				"client_id": "test-client",
				"client_secret": "test-secret",
			}
		)
		if platform_type == "Esalink":
			doc.update(
				{
					"esalink_environment": "test",
					"esalink_customer_id": "777",
					"esalink_user_id": "test-client",
					"esalink_customer_status": "ACTIVE",
				}
			)
		doc.flags.ignore_permissions = True
		doc.insert()
		return doc.name

	# ------------------------------------------------------------------ invoices

	def make_einvoice(self, customer: str, *, profile="EN16931", attach_pdf=True):
		"""Insert a draft Sales Invoice (which auto-creates its eInvoice) and return
		the eInvoice document.

		For CII/Factur-X sends we pre-attach an embedded PDF so ``_get_file_for_pa``
		reuses it instead of shelling out to wkhtmltopdf (which is unavailable/slow in
		test/CI). UBL invoices are sent as raw XML and need no attachment.
		"""
		currency = frappe.db.get_value("Company", COMPANY, "default_currency") or "EUR"
		si = frappe.new_doc("Sales Invoice")
		si.company = COMPANY
		si.customer = customer
		si.currency = currency
		si.posting_date = frappe.utils.today()
		si.etransaction_profile = profile
		si.append("items", {"item_code": "_Test Item 1", "qty": 1, "rate": 100.0})
		# A standard-rated VAT line so BT-152 > 0 (BR-S-05) and no exemption reason (BR-S-10).
		tax_account = frappe.db.get_value(
			"Account", {"account_type": "Tax", "company": COMPANY, "is_group": 0}, "name"
		)
		if tax_account:
			si.append(
				"taxes",
				{
					"charge_type": "On Net Total",
					"account_head": tax_account,
					"rate": 20.0,
					"description": "TVA 20%",
				},
			)
		si.flags.ignore_permissions = True
		si.insert()
		einvoice_name = frappe.db.exists("eInvoice", {"sales_invoice": si.name})
		self.assertTrue(einvoice_name, "Sales Invoice insert should have created an eInvoice")
		einvoice = frappe.get_doc("eInvoice", einvoice_name)
		if attach_pdf and einvoice.get("syntax") != "UBL":
			self._attach_embedded_pdf(einvoice)
		return einvoice

	def _attach_embedded_pdf(self, einvoice):
		"""Attach a minimal PDF as the eInvoice's embedded document so the Factur-X
		send path never invokes wkhtmltopdf."""
		from frappe.utils.file_manager import save_file

		file_doc = save_file(
			f"{einvoice.sales_invoice}.pdf",
			minimal_pdf_content(),
			"Sales Invoice",
			einvoice.sales_invoice,
			is_private=1,
		)
		einvoice.db_set("einvoice_embedded_document", file_doc.file_url)
