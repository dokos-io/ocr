# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

"""Seed a site so the Cypress suite under `cypress/integration/` can run against it.

Invoked once per CI job (and once per local site) with::

    bench --site <site> execute etransactions.tests.ui_test_fixtures.make_fixtures

and then, once frappe.tests.ui_test_helpers.create_test_user has created the Cypress
user::

    bench --site <site> execute erpnext.tests.ui_test_fixtures.align_test_user_timezone

Everything here is idempotent: re-running on a warm site must be a no-op.

The `@whitelist_for_tests` endpoints below are what the specs drive. They exist because
the inbound flow starts at an hourly cron talking to an accredited platform: a browser
cannot trigger that, and CI has neither a platform nor a background worker. They stub
the platform client and run the *real* ingestion code, so what the spec then asserts in
the UI was produced by the production path.
"""

import os
from unittest.mock import patch

import frappe
from frappe.tests.utils import whitelist_for_tests

from etransactions.tests.fixtures import (
	clear_platforms,
	ensure_default_expense_account,
	seed_company,
	seed_item,
)

# erpnext.tests.ui_test_fixtures owns this; re-declared rather than imported so a
# rename over there fails loudly here instead of silently seeding the wrong company.
COMPANY = "UI Test Co"

PLATFORM = "UI Test Platform"
# Seller of the Factur-X fixtures under tests/invoices — matching tax_id is what lets
# entity_resolver.resolve_supplier() bind the received invoice to a real Supplier, which
# is the whole point of asserting on "prefilled" data.
SUPPLIER = "LE FOURNISSEUR"
SUPPLIER_TAX_ID = "FR11123456782"

# EN 16931 rather than BASIC_WL: "WL" is *without lines*, and a Supplier Invoice with no
# item rows would make the prefill assertions vacuous.
FIXTURE_FOLDER = "3.en16931"
FIXTURE_INVOICE = "F20220023"


def make_fixtures():
	"""Entry point: bring the site to the state every spec assumes."""
	from erpnext.tests.ui_test_fixtures import make_fixtures as erpnext_fixtures

	# Company, chart of accounts, warehouses, items and parties.
	erpnext_fixtures()

	if not frappe.db.exists("Company", COMPANY):
		# erpnext_fixtures() only runs the setup wizard on a site where setup is not
		# complete, so pointing this at an existing business site silently skips the
		# company and everything below fails on an obscure link error instead.
		frappe.throw(
			f"{COMPANY} does not exist. The UI fixtures are meant for a dedicated, freshly "
			"created site (see the ui_tests job in .gitlab-ci.yml), not for a site that is "
			"already set up."
		)

	enable_einvoicing()
	allow_repeated_items()
	seed_company(COMPANY)
	ensure_default_expense_account(COMPANY)
	seed_item()
	make_supplier()
	make_platform()

	frappe.db.commit()  # nosemgrep


def enable_einvoicing():
	"""Turn the feature on, and turn off everything that would reach for a worker.

	`frappe.boot.einvoicing_enabled` is read when the desk boots, and every eTransactions
	field and panel is gated on it, so this has to be committed before the first cy.visit.
	"""
	settings = frappe.get_single("eTransactions Settings")
	settings.enable_einvoicing = 1
	# receive_incoming_flow() drives poll_incoming_flows() directly; make sure that
	# doesn't depend on the set_default_enable_receiving_einvoices patch having already
	# run on this (freshly created) site.
	settings.enable_receiving_einvoices = 1
	# create_purchase_invoice() otherwise refuses to build a PI without a submitted
	# Purchase Order, and the received invoice references none.
	settings.no_purchase_order = 1
	# The auto-sends enqueue a background job that would try to reach a platform.
	settings.auto_send_in_hand = 0
	settings.auto_send_approved = 0
	settings.auto_send_payment = 0
	settings.flags.ignore_permissions = True
	settings.save()


def allow_repeated_items():
	"""Let a Purchase Invoice carry the same item on several lines.

	The received lines carry the seller's product ids, which match no Dokos Item, so the
	specs pick the same test item for every line — and a Purchase Invoice refuses a
	repeated item unless Buying Settings allows it.
	"""
	frappe.db.set_single_value("Buying Settings", "allow_multiple_items", 1)


def make_supplier() -> str:
	if not frappe.db.exists("Supplier", SUPPLIER):
		frappe.get_doc(
			{
				"doctype": "Supplier",
				"supplier_name": SUPPLIER,
				"supplier_group": _supplier_group(),
				"country": "France",
				"tax_id": SUPPLIER_TAX_ID,
			}
		).insert(ignore_if_duplicate=True, ignore_permissions=True)
	else:
		frappe.db.set_value("Supplier", SUPPLIER, "tax_id", SUPPLIER_TAX_ID, update_modified=False)
	return SUPPLIER


def _supplier_group() -> str:
	return frappe.db.get_value("Supplier Group", {"is_group": 0}, "name") or "All Supplier Groups"


def make_platform() -> str:
	"""One active accredited platform, so poll_incoming_flows() has a company to poll.

	Its type is irrelevant: the fixture endpoints stub the client factory, and no HTTP
	is ever attempted.
	"""
	existing = frappe.db.get_value(
		"eTransactions Accredited Platform", {"company": COMPANY, "platform_name": PLATFORM}
	)
	if existing:
		frappe.db.set_value("eTransactions Accredited Platform", existing, "is_active", 1)
		return existing

	clear_platforms(COMPANY)
	platform = frappe.get_doc(
		{
			"doctype": "eTransactions Accredited Platform",
			"platform_name": PLATFORM,
			"platform_type": "Custom",
			"platform_code": "UITEST",
			"company": COMPANY,
			"transaction_type": "Both",
			"is_active": 1,
			"api_base_url": "http://localhost:1/ui-test-never-called",
			# validate() requires credentials; nothing ever authenticates with them.
			"client_id": "ui-test",
			"client_secret": "ui-test-secret",
		}
	)
	platform.flags.ignore_permissions = True
	platform.insert()
	return platform.name


# --------------------------------------------------------------------------- fixtures
# Endpoints the Cypress specs call through cy.call(...).


class _StubPlatformClient:
	"""Answers the two calls the inbound poller makes, from a local fixture file."""

	def __init__(self, flow, content: bytes):
		self.flow = flow
		self.content = content

	def list_incoming_invoices(self, updated_after=None):
		return [self.flow]

	def download_flow(self, flow_id):
		return self.content


def _fixture_pdf() -> bytes:
	# get_app_path scrubs its arguments, so the file name is joined separately.
	folder = frappe.get_app_path("etransactions", "tests", "invoices", FIXTURE_FOLDER)
	name = next(f for f in sorted(os.listdir(folder)) if FIXTURE_INVOICE in f)
	with open(os.path.join(folder, name), "rb") as f:
		return f.read()


def _commit():
	"""Persist for the browser, but never break a Python test's rollback isolation."""
	if not frappe.in_test:
		frappe.db.commit()  # nosemgrep


@whitelist_for_tests()
def receive_incoming_flow(flow_id: str | None = None, company: str | None = None) -> dict:
	"""Receive one e-invoice through the real inbound path, and return what it produced.

	Runs `poll_incoming_flows()` — the hourly cron itself, so the dedup, poll-window and
	eInvoicing Log bookkeeping are covered too — against a stub client, then downloads
	the content inline. Production enqueues that download; the UI job runs no worker, and
	a spec cannot wait on a job that will never be picked up.

	``company`` exists so the Python test can drive this against its own test company;
	the specs leave it at the UI-test company.
	"""
	from etransactions.components.superpdp.models import IncomingFlow
	from etransactions.plateforme_agreee.flow import fetch_einvoice_content, poll_incoming_flows

	company = company or COMPANY
	flow_id = flow_id or f"UI-FLOW-{frappe.generate_hash(length=8)}"
	flow = IncomingFlow(
		flow_id=flow_id,
		submitted_at=frappe.utils.now(),
		updated_at=None,
		flow_type="SupplierInvoice",
		syntax=None,
	)
	client = _StubPlatformClient(flow, _fixture_pdf())

	# Two patch targets, not one: flow.py binds get_client at import time (so the poller
	# reads flow.get_client), while eInvoice.fetch_content_from_platform() imports it
	# per call (so the download reads session.get_client).
	#
	# frappe.enqueue is a no-op here: the content fetch is done inline just below, and
	# leaving a queued job behind would race the assertions with a second parse.
	with (
		patch("etransactions.plateforme_agreee.flow.get_client", return_value=client),
		patch("etransactions.plateforme_agreee.session.get_client", return_value=client),
		patch("frappe.enqueue"),
	):
		poll_incoming_flows()

		# Filtered on the company as well as the flow id: the poller walks every company
		# with an active platform, and they all get handed the same stub flow.
		einvoice = frappe.db.get_value(
			"eInvoice",
			{"pa_flow_id": flow_id, "einvoice_type": "Incoming", "company": company},
			"name",
		)
		if not einvoice:
			frappe.throw(f"the poller did not record a flow for {flow_id} on {company}")

		fetch_einvoice_content(einvoice)

	_commit()

	return {
		"einvoice": einvoice,
		"supplier_invoice": frappe.db.get_value("Supplier Invoice", {"einvoice": einvoice}),
		"flow_id": flow_id,
	}


@whitelist_for_tests()
def record_lifecycle_event(einvoice: str, status: str = "in_hand") -> dict:
	"""Put one lifecycle event on the timeline without calling a platform.

	The Purchase Invoice renders the events the eInvoice has; with none, the spec cannot
	tell an empty timeline from a broken one.
	"""
	from etransactions.etransactions.doctype.einvoice_event.einvoice_event import record_event

	record_event(
		einvoice,
		direction="out",
		status=status,
		state="done",
		status_datetime=frappe.utils.now(),
		pa_flow_id=frappe.db.get_value("eInvoice", einvoice, "pa_flow_id"),
	)
	frappe.db.set_value("eInvoice", einvoice, "pa_status", "done", update_modified=False)
	_commit()

	return {"einvoice": einvoice, "status": status}


@whitelist_for_tests()
def reset_einvoicing() -> dict:
	"""Delete what a previous run received.

	testIsolation is off and CI retries specs, so a spec that receives an e-invoice must
	be safe to run twice against the same site. Deleted newest-first: the Purchase
	Invoice links the Supplier Invoice which links the eInvoice.
	"""
	deleted = {"Purchase Invoice": 0, "Supplier Invoice": 0, "eInvoice": 0}

	einvoices = frappe.get_all(
		"eInvoice", filters={"einvoice_type": "Incoming", "company": COMPANY}, pluck="name"
	)
	if not einvoices:
		return deleted

	supplier_invoices = frappe.get_all(
		"Supplier Invoice", filters={"einvoice": ["in", einvoices]}, pluck="name"
	)
	purchase_invoices = (
		frappe.get_all(
			"Purchase Invoice", filters={"supplier_invoice": ["in", supplier_invoices]}, pluck="name"
		)
		if supplier_invoices
		else []
	)

	for doctype, names in (
		("Purchase Invoice", purchase_invoices),
		("Supplier Invoice", supplier_invoices),
		("eInvoice", einvoices),
	):
		for name in names:
			frappe.delete_doc(
				doctype, name, force=True, ignore_permissions=True, delete_permanently=True
			)
			deleted[doctype] += 1

	_commit()
	return deleted
