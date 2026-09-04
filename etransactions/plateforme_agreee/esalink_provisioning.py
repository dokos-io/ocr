"""Esalink (HUBTIMIZE) account registration — create an account per Dokos company.

Uses HUBTIMIZE's partner Customer-management API (``/v1/customerPA``): when an Esalink
platform is added for a company we look the company up on Esalink by SIREN and, if it has
no customer yet, create one (which triggers Esalink's KYC/KYB onboarding email and
registers the French directory line), mint the company's API credentials, and persist them
on an **eTransactions Accredited Platform** record. A scheduled poll then flips the platform
active once Esalink validates the account.

The integrator (partner) credentials and the ``hubtimize-api-key`` are read from
``site_config`` (``esalink_api_key``, ``esalink_partner_username``,
``esalink_partner_password``) -- or, once this site's shared ``dokos_connector_*`` identity
(see :mod:`dokos_connector`) is configured, not read on this site at all: dokops holds them
and every partner call is forwarded through it instead. No separate opt-in flag decides
this -- exactly like Bridge's own cutover, whichever credentials are actually configured is
what gets used, and the connector is preferred when present. The minted per-company
``clientId``/``clientSecret`` live on each platform record either way and are what
:func:`session.get_client` uses for invoice operations.

The *environment* (``test`` / ``prod``, defaulting to ``prod``) is chosen per platform record
on its ``esalink_environment`` field — it is not a site-level setting. Both the partner client
and the per-company operations client resolve their base URL from the environment of the row
they act on, so an account is always minted on the host it will later be used against.
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, getdate

from etransactions.components.esalink import (
	EsalinkPartnerClient,
	EsalinkPartnerProxyClient,
	base_url_for_environment,
)
from etransactions.plateforme_agreee.dokos_connector import use_proxy

PROVISION_ROLES = ("System Manager", "Accounts Manager")

# Esalink requires the identifier start date to be at least 10 days in the future.
_START_DATE_OFFSET_DAYS = 11


# ---------------------------------------------------------------------------
# Configuration (credentials from site_config; environment from the platform record)
# ---------------------------------------------------------------------------


def esalink_api_key() -> str:
	"""The environment-agnostic ``hubtimize-api-key`` shared by both Esalink clients."""
	return frappe.conf.get("esalink_api_key") or ""


def esalink_partner_config(environment: str | None = None) -> dict:
	"""Partner credentials from ``site_config`` + the base URL for ``environment``.

	``environment`` comes from the platform record being acted on; omit it only when the
	caller inspects the credentials alone (see :func:`partner_credentials_configured`).

	When ``microcks_url`` is set in ``site_config`` (integration tests / CI) the base URL
	is redirected to the Esalink Customer API mock; inert otherwise.
	"""
	from etransactions.plateforme_agreee._microcks import microcks_base_url

	return {
		"base_url": microcks_base_url("EsalinkPartner") or base_url_for_environment(environment),
		"api_key": esalink_api_key(),
		"username": frappe.conf.get("esalink_partner_username") or "",
		"password": frappe.conf.get("esalink_partner_password") or "",
	}


def partner_credentials_configured() -> bool:
	"""True when partner-management calls are usable from this site.

	``use_proxy()`` already means the dokos connector is configured (the partner
	credentials themselves live only on dokops and are never checked here); otherwise this
	falls back to the 3 legacy partner credentials in ``site_config``.
	"""
	if use_proxy():
		return True
	cfg = esalink_partner_config()
	return bool(cfg["username"] and cfg["password"] and cfg["api_key"])


def _host_is_dokos_cloud(host: str) -> bool:
	"""True when ``host`` (site name or configured hostname) sits under ``.dokos.cloud``."""
	host = host.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
	return host.endswith(".dokos.cloud")


def _dokos_cloud_candidate_hosts() -> list:
	"""Hosts that identify a Dokos Cloud site — the configured hostname and the site name."""
	return [h for h in (frappe.conf.get("hostname"), getattr(frappe.local, "site", None)) if h]


def is_dokos_cloud() -> bool:
	"""True on Dokos Cloud.

	Prefers the explicit ``dokos_cloud`` site_config flag set by cloud provisioning;
	falls back to a ``.dokos.cloud`` host match (configured hostname / site name) so
	cloud sites still resolve when the flag is absent.
	"""
	if frappe.conf.get("dokos_cloud"):
		return True
	return any(_host_is_dokos_cloud(h) for h in _dokos_cloud_candidate_hosts())


def _partner_credentials_message() -> str:
	"""Audience-aware guidance shown when Esalink partner-management calls aren't usable.

	Reached only when neither the dokos connector nor the legacy site_config credentials
	are configured -- ``use_proxy()`` already covers the connector case.
	"""
	base = _("The Esalink partner credentials are not configured on this site.")
	if is_dokos_cloud():
		return base + " " + _("Send a message to help@dokos.cloud to enable Esalink.")
	return base + " " + _(
		"Contact your account manager at Esalink to obtain your partner credentials,"
		" then set esalink_partner_username, esalink_partner_password and"
		" esalink_api_key in site_config.json."
	)


@frappe.whitelist()
def esalink_partner_status() -> dict:
	"""Whether the Esalink partner credentials are configured, for the Add/Edit dialog.

	Callable without an existing platform record so the Add dialog can gate the
	Esalink selection before any row is created.
	"""
	frappe.only_for(PROVISION_ROLES)
	configured = partner_credentials_configured()
	return {
		"configured": configured,
		"is_cloud": is_dokos_cloud(),
		"message": None if configured else _partner_credentials_message(),
	}


def _partner_client(environment: str | None) -> "EsalinkPartnerClient | EsalinkPartnerProxyClient":
	"""Partner Customer-API client for ``environment`` — the one on the row being acted on.

	The credentials (or, in proxy mode, the dokos connector) are site-level but the host is
	not, so the environment must come from the platform record; passing the wrong one mints
	or reads an account on the wrong Esalink.
	"""
	if use_proxy():
		return EsalinkPartnerProxyClient(environment=environment or "prod")

	cfg = esalink_partner_config(environment)
	if not (cfg["username"] and cfg["password"] and cfg["api_key"]):
		frappe.throw(_partner_credentials_message())
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


def _resolve_routing_address(
	routing_address: str | None, default_value: str, default_scheme: str
) -> tuple[str, str]:
	"""Split the routing address into an Esalink ``(qualifier, value)`` electronic address.

	Falls back to ``default_value`` (the company's legal identifier) when no routing address is
	supplied. A bare identifier is filed under ``default_scheme`` — the scheme of the chosen
	legal-identifier type, so a SIRET lands under ``0009`` rather than the SIREN scheme. A
	``scheme:value`` identifier (e.g. ``0088:1234567890123`` for a Peppol address) carries its
	own scheme and is split as-is.
	"""
	from etransactions.plateforme_agreee.routing import identifier_to_electronic_address

	value = (routing_address or "").strip() or default_value
	if ":" in value:
		return identifier_to_electronic_address(value)
	return default_scheme or _LEGAL_ID_SCHEMES["siren"], value.strip()


# Legal identifier the company is registered under on Esalink → its CEF EAS scheme.
_LEGAL_ID_SCHEMES = {"siren": "0225", "siret": "0009"}


def _normalize_legal_id_type(legal_id_type: str | None) -> str:
	"""Coerce a legal-id-type input to a supported value (defaults to ``siren``)."""
	value = (legal_id_type or "").strip().lower()
	return value if value in _LEGAL_ID_SCHEMES else "siren"


def _legal_identifier(company: str, legal_id_type: str) -> tuple[str, str]:
	"""Return the ``(value, scheme)`` for the company's chosen legal identifier.

	``siren`` → (``Company.siren_number``, ``0225``); ``siret`` → (default
	``Address.siret_number``, ``0009``). The value may be blank when the source field is unset.
	"""
	legal_id_type = _normalize_legal_id_type(legal_id_type)
	scheme = _LEGAL_ID_SCHEMES[legal_id_type]
	if legal_id_type == "siret":
		address = _company_address(company)
		value = (address.get("siret_number") if address else "") or ""
	else:
		value = frappe.db.get_value("Company", company, "siren_number") or ""
	return value.strip(), scheme


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
	address = _company_address(company)
	has_siren = bool((co.get("siren_number") or "").strip())
	has_siret = bool((address.get("siret_number") if address else "") or "")
	if not (has_siren or has_siret):
		issues.append(_("No legal identifier (SIREN or SIRET)"))

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
	"customerLegalId": _("Legal identifier"),
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
	siren = (co.get("siren_number") or "").strip()
	return {
		"customerName": co.get("company_name") or company,
		"customerLegalId": siren,
		"siren": siren,
		"siret": ((address.get("siret_number") if address else "") or "").strip(),
		"customerVat": (co.get("tax_id") or "").strip(),
		"customerEmail": _company_email(company, address) or "",
		"addressLine1": (address.address_line1 if address else "") or "",
		"addressLine2": (address.get("address_line2") if address else "") or "",
		"postalCode": (address.pincode if address else "") or "",
		"city": (address.city if address else "") or "",
		"country": _country_iso(address.get("country")) if address else "FR",
	}


def _build_customer_payload(
	company: str,
	customer_data: dict | None = None,
	routing_address: str | None = None,
	legal_id_type: str = "siren",
) -> dict:
	"""Build (and validate) the ``CreateCustomerDTO``, merging the dialog's enhancements.

	Passing ``electronicAddresses`` makes Esalink register the directory line, so no separate
	identifier call is needed. The routing address (the directory line invoices are addressed
	to) defaults to the chosen legal identifier, filed under that identifier type's scheme
	(SIREN → 0225, SIRET → 0009); ``routing_address`` may override the identifier, and may carry
	its own ``scheme:value`` when it addresses something else (e.g. a Peppol address).

	API-user creation is deferred to the explicit :meth:`create_user` call in the registration
	flow (``apiUser="N"``): the inline user Esalink would create with ``apiUser="Y"`` is keyed
	off ``customerEmail`` (not guaranteed unique) and its credentials are not returned here, so
	it is both redundant and a 400 risk.
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

	legal_id = str(data["customerLegalId"]).strip()
	# The scheme is never part of the routing address the user sees: it follows from the chosen
	# legal-identifier type (SIREN → 0225, SIRET → 0009). An explicit routing_address still wins,
	# and may carry its own scheme when it addresses something else (e.g. a Peppol address).
	_, scheme = _legal_identifier(company, legal_id_type)
	qualifier, addressing_value = _resolve_routing_address(routing_address, legal_id, scheme)
	payload = {
		"customerName": data["customerName"],
		"customerLegalId": legal_id,
		"customerEmail": data["customerEmail"],
		"addressLine1": data["addressLine1"],
		"postalCode": data["postalCode"],
		"city": data["city"],
		"country": data["country"],
		"activationPA": "Y",
		"receptionPa": "Y",
		# "N": don't let Esalink create an inline API user (it 400s on the email-keyed
		# user creation). We mint the API credentials explicitly via create_user() below.
		"apiUser": "N",
		"electronicAddresses": [{"electronicAddress": addressing_value, "qualifier": qualifier}],
		"startDate": _start_date(),
	}
	if data.get("addressLine2"):
		payload["addressLine2"] = data["addressLine2"]
	if data.get("customerVat"):
		payload["customerVat"] = data["customerVat"]
	return payload


def _enhance_company(
	company: str, customer_data: dict | None, legal_id_type: str = "siren"
) -> None:
	"""Persist newly-supplied SIREN / VAT back onto the Company when it lacked them.

	Only write ``customerLegalId`` back to ``siren_number`` when the identifier is a SIREN — a
	SIRET (or any other scheme) must not be misfiled into the Company's SIREN field.
	"""
	if not customer_data:
		return
	co = frappe.get_doc("Company", company)
	updates = {}
	legal_id = (customer_data.get("customerLegalId") or "").strip()
	if (
		_normalize_legal_id_type(legal_id_type) == "siren"
		and legal_id
		and not (co.get("siren_number") or "").strip()
	):
		updates["siren_number"] = legal_id
	vat = (customer_data.get("customerVat") or "").strip()
	if vat and not (co.get("tax_id") or "").strip():
		updates["tax_id"] = vat
	if updates:
		frappe.db.set_value("Company", company, updates)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


_PLATFORM_FIELDS = [
	"name",
	"esalink_customer_id",
	"esalink_customer_status",
	"is_active",
	"esalink_environment",
]


def _existing_esalink_platform(company: str) -> dict | None:
	return frappe.db.get_value(
		"eTransactions Accredited Platform",
		{"company": company, "platform_type": "Esalink"},
		_PLATFORM_FIELDS,
		as_dict=True,
	)


def _target_esalink_platform(company: str, platform_name: str | None) -> dict | None:
	"""Resolve the Esalink platform row to register: the named row, else the company's one."""
	if platform_name:
		return frappe.db.get_value(
			"eTransactions Accredited Platform",
			platform_name,
			_PLATFORM_FIELDS,
			as_dict=True,
		)
	return _existing_esalink_platform(company)


def _platform_environment(platform_name: str) -> str:
	"""The environment one platform row operates against (``prod`` when unset)."""
	return (
		frappe.db.get_value(
			"eTransactions Accredited Platform", platform_name, "esalink_environment"
		)
		or "prod"
	)


@frappe.whitelist()
def esalink_registration_prefill(company: str, platform_name: str | None = None) -> dict:
	"""Prefill for the Esalink registration dialog: company data + readiness + gate flag.

	Returns both the ``siren`` and ``siret`` so the dialog can switch ``customerLegalId`` when
	the legal-identifier type changes. When ``platform_name`` is given, the persisted
	``legal_id_type`` is returned so an edit restores the previous choice (default ``siren``).
	"""
	frappe.only_for(PROVISION_ROLES)
	data = _company_base_customer_data(company)
	data["issues"] = check_company_provisioning_readiness(company)
	data["partner_ready"] = partner_credentials_configured()
	data["legal_id_type"] = "siren"
	if platform_name:
		stored = frappe.db.get_value(
			"eTransactions Accredited Platform", platform_name, "esalink_legal_id_type"
		)
		data["legal_id_type"] = _normalize_legal_id_type(stored)
	return data


@frappe.whitelist()
def esalink_registration_status(platform_name: str) -> dict:
	"""Registration state of one Esalink platform, for the edit dialog's status banner.

	``registered`` is driven by the presence of an Esalink customer id. ``routing_address`` is
	the row's persisted legal identifier (the SIREN or the SIRET) — the same address registration
	uses by default — without an Esalink API call. Its scheme is not shown: it follows from
	``legal_id_type``.
	"""
	frappe.only_for(PROVISION_ROLES)
	row = frappe.db.get_value(
		"eTransactions Accredited Platform",
		platform_name,
		[
			"company",
			"esalink_customer_id",
			"esalink_customer_status",
			"is_active",
			"esalink_environment",
			"esalink_legal_id_type",
		],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Platform {0} not found.").format(platform_name))

	legal_id_type = _normalize_legal_id_type(row.esalink_legal_id_type)
	legal_id, _scheme = _legal_identifier(row.company, legal_id_type)
	siren = (frappe.db.get_value("Company", row.company, "siren_number") or "").strip()
	return {
		"registered": bool(row.esalink_customer_id),
		"customer_id": row.esalink_customer_id,
		"customer_status": row.esalink_customer_status,
		"is_active": bool(row.is_active),
		"environment": row.esalink_environment,
		"legal_id_type": legal_id_type,
		"siren": siren,
		"routing_address": legal_id,
	}


@frappe.whitelist()
def register_esalink_company(
	company: str,
	transaction_type: str = "Both",
	customer_data=None,
	routing_address: str | None = None,
	platform_name: str | None = None,
	legal_id_type: str = "siren",
) -> dict:
	"""Register one company on Esalink and persist its platform record.

	Idempotent: a platform that already has a customer id is returned untouched. Otherwise
	the company is looked up on Esalink by its legal identifier — an existing customer is
	reused, else one is created (KYC email + directory line addressed to ``routing_address``,
	which defaults to the chosen ``legal_id_type`` under its scheme: SIREN → 0225, SIRET →
	0009). Its API credentials are minted and written to an eTransactions Accredited Platform
	record (inactive until Esalink validates), then the integration is tested.

	When ``platform_name`` is given the registration updates *that* exact platform row (a
	company may hold both a Sales and a Purchases Esalink row); otherwise the company's single
	Esalink platform is looked up / created.

	The account is minted on the environment already selected on the target row (``prod`` for a
	row that does not exist yet), so it lands on the host the row will later operate against.
	"""
	frappe.only_for(PROVISION_ROLES)
	if isinstance(customer_data, str):
		customer_data = json.loads(customer_data) if customer_data.strip() else None
	legal_id_type = _normalize_legal_id_type(legal_id_type)

	existing = _target_esalink_platform(company, platform_name)
	if existing and existing.get("esalink_customer_id"):
		return {
			"company": company,
			"platform_name": existing.get("name"),
			"customer_id": existing.get("esalink_customer_id"),
			"state": "existing",
			"status": existing.get("esalink_customer_status"),
		}

	_enhance_company(company, customer_data, legal_id_type)
	payload = _build_customer_payload(company, customer_data, routing_address, legal_id_type)
	legal_id = payload["customerLegalId"]

	environment = (existing or {}).get("esalink_environment") or "prod"
	partner = _partner_client(environment)

	# Reuse the company's Esalink customer if it already exists (matched by its legal id),
	# otherwise create it (triggers the KYC email + directory line).
	customer_id = partner.find_customer_by_legal_id(legal_id)
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
			# Written back unchanged — pins the row to the host the account was minted on.
			"esalink_environment": environment,
			"esalink_legal_id_type": legal_id_type,
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
	was_active = frappe.db.get_value("eTransactions Accredited Platform", platform_name, "is_active")
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
	if values.get("is_active") and not was_active:
		_default_auto_send_settings()
		company = frappe.db.get_value("eTransactions Accredited Platform", platform_name, "company")
		if company:
			_send_pending_in_hand_statuses(company)


def _default_auto_send_settings() -> None:
	"""Default the lifecycle auto-send flags on the first time a PA connection activates.

	The eTransactions Settings singleton can already exist with these flags at 0 (e.g.
	created on a site before the fields' JSON default of 1 was added) — a JSON default
	only applies when the document is first created, never retroactively. Set them here,
	right as a platform goes active for the first time, so a newly-connected company
	doesn't silently end up with lifecycle reporting to the platform switched off.
	"""
	for field in ("auto_send_in_hand", "auto_send_approved", "auto_send_payment"):
		if frappe.get_single_value("eTransactions Settings", field):
			continue
		frappe.db.set_single_value("eTransactions Settings", field, 1)


def _send_pending_in_hand_statuses(company: str) -> None:
	"""Catch up 'in_hand' sends skipped because no platform was active yet.

	A Supplier Invoice created from an incoming e-invoice while the company's PA
	connection was still activating never gets a second chance: its 'in_hand' send
	is attempted once, at Supplier Invoice creation (see
	``auto_status.on_supplier_invoice_after_insert``), and silently skipped if no
	active platform is found at that moment. Re-run the same eligibility check here,
	right as the platform goes active, so those invoices are not left behind.
	"""
	from etransactions.plateforme_agreee.auto_status import _send

	if not frappe.get_single_value("eTransactions Settings", "auto_send_in_hand"):
		return
	einvoice_names = set(
		frappe.get_all(
			"Supplier Invoice",
			filters={"company": company, "einvoice": ["is", "set"]},
			pluck="einvoice",
		)
	)
	for einvoice_name in einvoice_names:
		ei = frappe.db.get_value(
			"eInvoice", einvoice_name, ["name", "einvoice_type", "pa_flow_id"], as_dict=True
		)
		if ei and ei.einvoice_type == "Incoming" and ei.pa_flow_id:
			_send(ei.name, "in_hand", "purchases")


@frappe.whitelist()
def refresh_customer_status(platform_name: str) -> dict:
	"""Poll Esalink for one platform's account status and store it."""
	frappe.only_for(PROVISION_ROLES)
	customer_id = frappe.db.get_value(
		"eTransactions Accredited Platform", platform_name, "esalink_customer_id"
	)
	if not customer_id:
		frappe.throw(_("This platform has no Esalink customer id to refresh."))

	partner = _partner_client(_platform_environment(platform_name))
	data = partner.get_customer(int(customer_id)) or {}
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
	_partner_client(_platform_environment(platform_name)).resend_kyc_email(int(customer_id))
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
		fields=["name", "esalink_customer_id", "esalink_environment"],
	)
	if not pending:
		return
	# Partner credentials are site-level but the host is not, so one client per environment.
	# Built up front (outside the per-row guard) so missing credentials still fail loudly once.
	environments = dict.fromkeys(row.esalink_environment or "prod" for row in pending)
	clients = {env: _partner_client(env) for env in environments}
	for row in pending:
		try:
			client = clients[row.esalink_environment or "prod"]
			data = client.get_customer(int(row.esalink_customer_id)) or {}
			_apply_customer_status(
				row.name, data.get("activationStatus"), data.get("stateReason")
			)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(
				frappe.get_traceback(), f"Esalink status poll failed: {row.name}"
			)
