"""Esalink (HUBTIMIZE) account registration — create an account per Dokos company.

Uses HUBTIMIZE's partner Customer-management API (``/v1/customerPA``): when an Esalink
platform is added for a company we look the company up on Esalink by SIREN and, if it has
no customer yet, create one (which triggers Esalink's KYC/KYB onboarding email and
registers the French directory line), mint the company's API credentials, and persist them
on an **eTransactions Accredited Platform** record. A scheduled poll then flips the platform
active once Esalink validates the account.

The integrator (partner) credentials and the environment-level ``hubtimize-api-key`` are
read from ``site_config`` (``esalink_environment``, ``esalink_api_key``,
``esalink_partner_username``, ``esalink_partner_password``); the minted per-company
``clientId``/``clientSecret`` live on each platform record and are what
:func:`session.get_client` uses for invoice operations.
"""

import json

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
# Configuration (site_config only)
# ---------------------------------------------------------------------------


def esalink_runtime_config() -> dict:
	"""Environment-level config used by the per-company operations client.

	Returns ``{"environment", "api_key"}`` from ``site_config`` — the base URL is derived
	from the environment by :func:`session._build_client` (or overridden by the platform
	record's ``esalink_environment`` / ``api_base_url``).
	"""
	return {
		"environment": frappe.conf.get("esalink_environment") or "test",
		"api_key": frappe.conf.get("esalink_api_key") or "",
	}


def esalink_partner_config() -> dict:
	"""Partner credentials + resolved base URL for the Customer-management API (site_config)."""
	env = frappe.conf.get("esalink_environment") or "test"
	return {
		"environment": env,
		"base_url": base_url_for_environment(env),
		"api_key": frappe.conf.get("esalink_api_key") or "",
		"username": frappe.conf.get("esalink_partner_username") or "",
		"password": frappe.conf.get("esalink_partner_password") or "",
	}


def partner_credentials_configured() -> bool:
	"""True when the 3 partner credentials are present in ``site_config``."""
	cfg = esalink_partner_config()
	return bool(cfg["username"] and cfg["password"] and cfg["api_key"])


def _partner_client() -> EsalinkPartnerClient:
	cfg = esalink_partner_config()
	if not (cfg["username"] and cfg["password"] and cfg["api_key"]):
		frappe.throw(
			_(
				"Configure the Esalink partner username, password and API key in"
				" site_config.json (esalink_partner_username, esalink_partner_password,"
				" esalink_api_key) first."
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


def _resolve_routing_address(routing_address: str | None, siren: str) -> tuple[str, str]:
	"""Split the routing address into an Esalink ``(qualifier, value)`` electronic address.

	Defaults to the SIREN under the French SIRENE scheme (``0225``). A supplied
	``routing_address`` may be a bare identifier (kept under ``0225``) or a ``scheme:value``
	identifier (e.g. ``0088:1234567890123`` for a Peppol address).
	"""
	from etransactions.plateforme_agreee.routing import identifier_to_electronic_address

	value = (routing_address or "").strip() or siren
	scheme, addressing_value = identifier_to_electronic_address(value)
	return scheme, addressing_value


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


def check_company_provisioning_readiness(company: str) -> list[str]:
	"""Company-data issues that would block registering it on Esalink.

	Surfaced (non-blocking) by the registration dialog's prefill; the actual payload
	builder re-validates the merged data (which may enhance the company) before sending.
	"""
	issues: list[str] = []
	co = frappe.get_doc("Company", company)
	if not (co.get("siren_number") or "").strip():
		issues.append(_("No SIREN number"))

	address = _company_address(company)
	if not address:
		issues.append(_("No default address"))
	else:
		missing = [f for f in ("address_line1", "city", "pincode") if not address.get(f)]
		if missing:
			issues.append(_("Incomplete address (missing: {0})").format(", ".join(missing)))

	if not _company_email(company, address):
		issues.append(_("No contact email (needed for the KYC onboarding email)"))

	return issues


# Registration fields the dialog may supply to enhance/complete the company data.
_CUSTOMER_DATA_KEYS = (
	"customerName",
	"customerLegalId",
	"customerVat",
	"customerEmail",
	"addressLine1",
	"addressLine2",
	"postalCode",
	"city",
	"country",
)

# Fields required by Esalink's CreateCustomerDTO (label used in the "missing data" error).
_REQUIRED_PAYLOAD_FIELDS = {
	"customerName": _("Company name"),
	"customerLegalId": _("SIREN"),
	"customerEmail": _("Contact email"),
	"addressLine1": _("Address line 1"),
	"postalCode": _("Postal code"),
	"city": _("City"),
	"country": _("Country"),
}


def _company_base_customer_data(company: str) -> dict:
	"""Best-effort customer data derived from the Company (may contain blanks)."""
	co = frappe.get_doc("Company", company)
	address = _company_address(company)
	return {
		"customerName": co.get("company_name") or company,
		"customerLegalId": (co.get("siren_number") or "").strip(),
		"customerVat": (co.get("tax_id") or "").strip(),
		"customerEmail": _company_email(company, address) or "",
		"addressLine1": (address.address_line1 if address else "") or "",
		"addressLine2": (address.get("address_line2") if address else "") or "",
		"postalCode": (address.pincode if address else "") or "",
		"city": (address.city if address else "") or "",
		"country": _country_iso(address.get("country")) if address else "FR",
	}


def _build_customer_payload(
	company: str, customer_data: dict | None = None, routing_address: str | None = None
) -> dict:
	"""Build (and validate) the ``CreateCustomerDTO``, merging the dialog's enhancements.

	Passing ``electronicAddresses`` makes Esalink register the directory line, so no separate
	identifier call is needed. The routing address (the directory line invoices are addressed
	to) defaults to the SIREN under the French SIRENE scheme (0225); ``routing_address`` may
	override it with a ``scheme:value`` identifier (e.g. a SIRET or a Peppol address).
	"""
	data = _company_base_customer_data(company)
	if customer_data:
		for key in _CUSTOMER_DATA_KEYS:
			value = customer_data.get(key)
			if value not in (None, ""):
				data[key] = value.strip() if isinstance(value, str) else value

	missing = [label for field, label in _REQUIRED_PAYLOAD_FIELDS.items() if not data.get(field)]
	if missing:
		frappe.throw(
			_("Cannot register {0} on Esalink — missing data: {1}").format(
				company, ", ".join(missing)
			)
		)

	siren = str(data["customerLegalId"]).strip()
	qualifier, addressing_value = _resolve_routing_address(routing_address, siren)
	payload = {
		"customerName": data["customerName"],
		"customerLegalId": siren,
		"customerEmail": data["customerEmail"],
		"addressLine1": data["addressLine1"],
		"postalCode": data["postalCode"],
		"city": data["city"],
		"country": data["country"],
		"activationPA": "Y",
		"receptionPa": "Y",
		"apiUser": "Y",
		"electronicAddresses": [{"electronicAddress": addressing_value, "qualifier": qualifier}],
		"startDate": _start_date(),
	}
	if data.get("addressLine2"):
		payload["addressLine2"] = data["addressLine2"]
	if data.get("customerVat"):
		payload["customerVat"] = data["customerVat"]
	return payload


def _enhance_company(company: str, customer_data: dict | None) -> None:
	"""Persist newly-supplied SIREN / VAT back onto the Company when it lacked them."""
	if not customer_data:
		return
	co = frappe.get_doc("Company", company)
	updates = {}
	siren = (customer_data.get("customerLegalId") or "").strip()
	if siren and not (co.get("siren_number") or "").strip():
		updates["siren_number"] = siren
	vat = (customer_data.get("customerVat") or "").strip()
	if vat and not (co.get("tax_id") or "").strip():
		updates["tax_id"] = vat
	if updates:
		frappe.db.set_value("Company", company, updates)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def _existing_esalink_platform(company: str) -> dict | None:
	return frappe.db.get_value(
		"eTransactions Accredited Platform",
		{"company": company, "platform_type": "Esalink"},
		["name", "esalink_customer_id", "esalink_customer_status", "is_active"],
		as_dict=True,
	)


def _target_esalink_platform(company: str, platform_name: str | None) -> dict | None:
	"""Resolve the Esalink platform row to register: the named row, else the company's one."""
	if platform_name:
		return frappe.db.get_value(
			"eTransactions Accredited Platform",
			platform_name,
			["name", "esalink_customer_id", "esalink_customer_status", "is_active"],
			as_dict=True,
		)
	return _existing_esalink_platform(company)


@frappe.whitelist()
def esalink_registration_prefill(company: str) -> dict:
	"""Prefill for the Esalink registration dialog: company data + readiness + gate flag."""
	frappe.only_for(PROVISION_ROLES)
	data = _company_base_customer_data(company)
	data["esalink_environment"] = esalink_runtime_config()["environment"]
	data["issues"] = check_company_provisioning_readiness(company)
	data["partner_ready"] = partner_credentials_configured()
	return data


@frappe.whitelist()
def esalink_registration_status(platform_name: str) -> dict:
	"""Registration state of one Esalink platform, for the edit dialog's status banner.

	``registered`` is driven by the presence of an Esalink customer id. ``routing_address``
	is derived from the row's Company SIREN (``0225:<siren>``) — the same address registration
	uses by default — without an Esalink API call.
	"""
	frappe.only_for(PROVISION_ROLES)
	row = frappe.db.get_value(
		"eTransactions Accredited Platform",
		platform_name,
		["company", "esalink_customer_id", "esalink_customer_status", "is_active", "esalink_environment"],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Platform {0} not found.").format(platform_name))

	siren = (frappe.db.get_value("Company", row.company, "siren_number") or "").strip()
	return {
		"registered": bool(row.esalink_customer_id),
		"customer_id": row.esalink_customer_id,
		"customer_status": row.esalink_customer_status,
		"is_active": bool(row.is_active),
		"environment": row.esalink_environment,
		"siren": siren,
		"routing_address": f"0225:{siren}" if siren else "",
	}


@frappe.whitelist()
def register_esalink_company(
	company: str,
	transaction_type: str = "Both",
	customer_data=None,
	routing_address: str | None = None,
	platform_name: str | None = None,
) -> dict:
	"""Register one company on Esalink and persist its platform record.

	Idempotent: a platform that already has a customer id is returned untouched. Otherwise
	the company is looked up on Esalink by SIREN — an existing customer is reused, else one
	is created (KYC email + directory line addressed to ``routing_address``, default SIREN).
	Its API credentials are minted and written to an eTransactions Accredited Platform record
	(inactive until Esalink validates), then the integration is tested.

	When ``platform_name`` is given the registration updates *that* exact platform row (a
	company may hold both a Sales and a Purchases Esalink row); otherwise the company's single
	Esalink platform is looked up / created.
	"""
	frappe.only_for(PROVISION_ROLES)
	if isinstance(customer_data, str):
		customer_data = json.loads(customer_data) if customer_data.strip() else None

	existing = _target_esalink_platform(company, platform_name)
	if existing and existing.get("esalink_customer_id"):
		return {
			"company": company,
			"platform_name": existing.get("name"),
			"customer_id": existing.get("esalink_customer_id"),
			"state": "existing",
			"status": existing.get("esalink_customer_status"),
		}

	_enhance_company(company, customer_data)
	payload = _build_customer_payload(company, customer_data, routing_address)
	siren = payload["customerLegalId"]

	partner = _partner_client()

	# Reuse the company's Esalink customer if it already exists (matched by SIREN),
	# otherwise create it (triggers the KYC email + directory line).
	customer_id = partner.find_customer_by_legal_id(siren)
	reused = customer_id is not None
	if not reused:
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
			"esalink_environment": esalink_runtime_config()["environment"],
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

	# Test the integration (probe the minted credentials). Non-blocking: the account may
	# still be WAITING_VALIDATION, but the token call confirms the credentials are usable.
	from etransactions.plateforme_agreee.session import check_platform_health

	health = check_platform_health(doc.name)

	return {
		"company": company,
		"platform_name": doc.name,
		"customer_id": str(customer_id),
		"state": "reused" if reused else "created",
		"status": "WAITING_VALIDATION",
		"health_status": health.get("status"),
		"health_message": health.get("message"),
	}


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
	# Partner credentials are site-level, so one client serves every pending platform.
	partner = _partner_client()
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
