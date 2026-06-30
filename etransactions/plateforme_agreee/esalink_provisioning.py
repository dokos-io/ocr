"""Esalink (HUBTIMIZE) account provisioning — create an account per Dokos company.

Uses HUBTIMIZE's partner Customer-management API (``/v1/customerPA``) to streamline
onboarding: for each company we create a customer (which triggers Esalink's KYC/KYB
onboarding email and registers the French directory line), mint the company's API
credentials, and persist them on an **eTransactions Accredited Platform** record. A
scheduled poll then flips the platform active once Esalink validates the account.

The integrator (partner) credentials and the environment-level ``hubtimize-api-key``
live on **eTransactions Settings**; the minted per-company ``clientId``/``clientSecret``
live on each platform record and are what :func:`session.get_client` uses for invoice
operations.
"""

import frappe
from frappe import _
from frappe.utils import add_days, getdate

from etransactions.components.esalink import (
	EsalinkPartnerClient,
	base_url_for_environment,
)

PROVISION_ROLES = ("System Manager", "Accounts Manager")

# Esalink requires the identifier start date to be at least 10 days in the future.
_START_DATE_OFFSET_DAYS = 11


# ---------------------------------------------------------------------------
# Configuration (eTransactions Settings)
# ---------------------------------------------------------------------------


def _settings():
	return frappe.get_single("eTransactions Settings")


def esalink_runtime_config() -> dict:
	"""Environment-level config used by the per-company operations client.

	Returns ``{"environment", "api_key"}`` — the base URL is derived from the
	environment by :func:`session._build_client` (or overridden by ``api_base_url``).
	"""
	s = _settings()
	return {
		"environment": s.get("esalink_environment") or "test",
		"api_key": s.get_password("esalink_api_key", raise_exception=False) or "",
	}


def esalink_partner_config() -> dict:
	"""Partner credentials + resolved base URL for the Customer-management API."""
	s = _settings()
	env = s.get("esalink_environment") or "test"
	return {
		"environment": env,
		"base_url": base_url_for_environment(env),
		"api_key": s.get_password("esalink_api_key", raise_exception=False) or "",
		"username": s.get("esalink_partner_username") or "",
		"password": s.get_password("esalink_partner_password", raise_exception=False)
		or "",
	}


def _partner_client() -> EsalinkPartnerClient:
	cfg = esalink_partner_config()
	if not (cfg["username"] and cfg["password"] and cfg["api_key"]):
		frappe.throw(
			_(
				"Configure the Esalink partner username, password and API key in eTransactions Settings first."
			)
		)
	return EsalinkPartnerClient(
		username=cfg["username"],
		password=cfg["password"],
		api_key=cfg["api_key"],
		base_url=cfg["base_url"],
	)


# ---------------------------------------------------------------------------
# Company → CreateCustomerDTO mapping
# ---------------------------------------------------------------------------


def _start_date() -> str:
	"""Identifier start date in ``DD-MM-YYYY`` (Esalink requires ≥10 days ahead)."""
	return getdate(add_days(None, _START_DATE_OFFSET_DAYS)).strftime("%d-%m-%Y")


def _country_iso(country_name: str | None) -> str:
	"""Map a Frappe Country name to its 2-letter ISO code (default ``FR``)."""
	if not country_name:
		return "FR"
	code = frappe.db.get_value("Country", country_name, "code")
	return (code or "fr").upper()[:2]


def _company_address(company: str):
	from frappe.contacts.doctype.address.address import get_default_address

	name = get_default_address("Company", company)
	return frappe.get_doc("Address", name) if name else None


def _company_email(company: str, address) -> str | None:
	"""Resolve the email Esalink will send the KYC onboarding link to."""
	if address and address.get("email_id"):
		return address.email_id
	contact = frappe.db.get_value(
		"Dynamic Link",
		{"link_doctype": "Company", "link_name": company, "parenttype": "Contact"},
		"parent",
	)
	if contact:
		return frappe.db.get_value("Contact", contact, "email_id")
	return None


def _company_customer_payload(company: str) -> dict:
	"""Build the ``CreateCustomerDTO`` for a company, validating required data.

	Passing ``electronicAddresses`` makes Esalink register the directory line (0225
	scheme = French SIRENE), so no separate identifier call is needed.
	"""
	co = frappe.get_doc("Company", company)
	siren = (co.get("siren_number") or "").strip()
	if not siren:
		frappe.throw(
			_(
				"Company {0} has no SIREN number — set it before provisioning Esalink."
			).format(company)
		)

	address = _company_address(company)
	if not address:
		frappe.throw(
			_(
				"Company {0} has no default address — required for Esalink provisioning."
			).format(company)
		)

	missing = [f for f in ("address_line1", "city", "pincode") if not address.get(f)]
	if missing:
		frappe.throw(
			_("Company {0} address is incomplete (missing: {1}).").format(
				company, ", ".join(missing)
			)
		)

	email = _company_email(company, address)
	if not email:
		frappe.throw(
			_(
				"No contact email found for company {0} — Esalink needs it to send the KYC onboarding email."
			).format(company)
		)

	payload = {
		"customerName": co.get("company_name") or company,
		"customerLegalId": siren,
		"customerEmail": email,
		"addressLine1": address.address_line1,
		"postalCode": address.pincode,
		"city": address.city,
		"country": _country_iso(address.get("country")),
		"activationPA": "Y",
		"receptionPa": "Y",
		"apiUser": "Y",
		"electronicAddresses": [{"electronicAddress": siren, "qualifier": "0225"}],
		"startDate": _start_date(),
	}
	if address.get("address_line2"):
		payload["addressLine2"] = address.address_line2
	if co.get("tax_id"):
		payload["customerVat"] = co.tax_id
	return payload


# ---------------------------------------------------------------------------
# Provisioning
# ---------------------------------------------------------------------------


def _existing_esalink_platform(company: str) -> dict | None:
	return frappe.db.get_value(
		"eTransactions Accredited Platform",
		{"company": company, "platform_type": "Esalink"},
		["name", "esalink_customer_id", "esalink_customer_status", "is_active"],
		as_dict=True,
	)


def provision_company(company: str, transaction_type: str = "Both") -> dict:
	"""Create the Esalink account for one company and persist its platform record.

	Idempotent: a company that already has an Esalink platform with a customer id is
	returned untouched. Otherwise creates the customer (KYC email + directory line),
	mints the API credentials, and writes an eTransactions Accredited Platform record
	(inactive until Esalink validates the account).
	"""
	existing = _existing_esalink_platform(company)
	if existing and existing.get("esalink_customer_id"):
		return {
			"company": company,
			"platform_name": existing.get("name"),
			"customer_id": existing.get("esalink_customer_id"),
			"state": "existing",
			"status": existing.get("esalink_customer_status"),
		}

	partner = _partner_client()
	payload = _company_customer_payload(company)

	customer_id = partner.create_customer(payload)
	creds = partner.create_user(customer_id) or {}
	client_id = creds.get("clientId")
	client_secret = creds.get("clientSecret")
	if not (client_id and client_secret):
		frappe.throw(
			_("Esalink did not return API credentials for company {0}.").format(company)
		)

	doc = (
		frappe.get_doc("eTransactions Accredited Platform", existing.get("name"))
		if existing
		else frappe.new_doc("eTransactions Accredited Platform")
	)
	doc.update(
		{
			"platform_name": doc.get("platform_name") or f"Esalink — {company}",
			"platform_type": "Esalink",
			"company": company,
			"transaction_type": transaction_type,
			"is_active": 0,  # activated by the status poll once Esalink validates
			"client_id": client_id,
			"client_secret": client_secret,
			"esalink_customer_id": str(customer_id),
			"esalink_user_id": client_id,
			"esalink_customer_status": "WAITING_VALIDATION",
		}
	)
	doc.flags.ignore_permissions = True
	doc.save()

	return {
		"company": company,
		"platform_name": doc.name,
		"customer_id": str(customer_id),
		"state": "created",
		"status": "WAITING_VALIDATION",
	}


@frappe.whitelist()
def bulk_provision_esalink(
	companies=None, transaction_type: str = "Both"
) -> list[dict]:
	"""Provision an Esalink account for several companies in one action.

	``companies`` is an optional JSON list / comma string; when omitted, every company
	without an Esalink account is targeted. Each company is provisioned independently —
	a failure on one is reported in its row and does not abort the others.
	"""
	frappe.only_for(PROVISION_ROLES)

	targets = _resolve_company_list(companies)
	results = []
	for company in targets:
		try:
			results.append(
				provision_company(company, transaction_type=transaction_type)
			)
			frappe.db.commit()
		except Exception as e:
			frappe.db.rollback()
			frappe.log_error(
				frappe.get_traceback(), f"Esalink provisioning failed: {company}"
			)
			results.append(
				{
					"company": company,
					"state": "error",
					"status": None,
					"message": str(e),
				}
			)
	return results


def _resolve_company_list(companies) -> list[str]:
	if isinstance(companies, str):
		companies = companies.strip()
		if companies.startswith("["):
			import json

			companies = json.loads(companies)
		elif companies:
			companies = [c.strip() for c in companies.split(",") if c.strip()]
		else:
			companies = None
	if companies:
		return list(companies)
	# Default: every company that has no Esalink platform yet.
	wired = set(
		frappe.get_all(
			"eTransactions Accredited Platform",
			filters={"platform_type": "Esalink"},
			pluck="company",
		)
	)
	return [c for c in frappe.get_all("Company", pluck="name") if c not in wired]


# ---------------------------------------------------------------------------
# Account status
# ---------------------------------------------------------------------------


def _apply_customer_status(
	platform_name: str, status: str | None, reason: str | None = None
) -> None:
	"""Persist the Esalink activation status; activate the platform once ACTIVE."""
	values = {"esalink_customer_status": status or "WAITING_VALIDATION"}
	if status == "ACTIVE":
		values["is_active"] = 1
	elif status in ("REJECTED", "INACTIVE"):
		values["is_active"] = 0
	if reason:
		values["last_health_message"] = reason[:140]
	frappe.db.set_value(
		"eTransactions Accredited Platform",
		platform_name,
		values,
		update_modified=False,
	)


@frappe.whitelist()
def refresh_customer_status(platform_name: str) -> dict:
	"""Poll Esalink for one platform's account status and store it."""
	frappe.only_for(PROVISION_ROLES)
	customer_id = frappe.db.get_value(
		"eTransactions Accredited Platform", platform_name, "esalink_customer_id"
	)
	if not customer_id:
		frappe.throw(_("This platform has no Esalink customer id to refresh."))

	data = _partner_client().get_customer(int(customer_id)) or {}
	status = data.get("activationStatus")
	_apply_customer_status(platform_name, status, data.get("stateReason"))
	frappe.db.commit()
	return {"status": status, "reason": data.get("stateReason")}


@frappe.whitelist()
def resend_kyc_email(platform_name: str) -> dict:
	"""Re-send Esalink's KYC/KYB onboarding email for a platform's customer account."""
	frappe.only_for(PROVISION_ROLES)
	customer_id = frappe.db.get_value(
		"eTransactions Accredited Platform", platform_name, "esalink_customer_id"
	)
	if not customer_id:
		frappe.throw(_("This platform has no Esalink customer id."))
	_partner_client().resend_kyc_email(int(customer_id))
	return {"status": "ok"}


def poll_esalink_customer_statuses():
	"""Hourly scheduler: refresh the account status of pending Esalink platforms."""
	pending = frappe.get_all(
		"eTransactions Accredited Platform",
		filters={
			"platform_type": "Esalink",
			"esalink_customer_status": ["in", ["WAITING_VALIDATION", ""]],
			"esalink_customer_id": ["is", "set"],
		},
		fields=["name", "esalink_customer_id"],
	)
	if not pending:
		return
	try:
		partner = _partner_client()
	except Exception:
		return  # partner credentials not configured yet — nothing to poll
	for row in pending:
		try:
			data = partner.get_customer(int(row.esalink_customer_id)) or {}
			_apply_customer_status(
				row.name, data.get("activationStatus"), data.get("stateReason")
			)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(
				frappe.get_traceback(), f"Esalink status poll failed: {row.name}"
			)
