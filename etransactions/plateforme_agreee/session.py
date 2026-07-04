import frappe
from frappe import _
from frappe.utils import now_datetime


# Per-platform-type capabilities.
#   ``self_provision`` advertises an in-app account-creation flow; all current
#   platforms register credentials in their own portal (manual), but the guided
#   dialog reads this map so an automated branch can be switched on per platform
#   later without UI rework.
#   ``ereporting`` advertises B2C/payment e-reporting to the PPF. Only SuperPDP
#   exposes the e-reporting endpoints today; CDAR platforms (Esalink/AFNOR) do
#   not, so callers must gate on this flag before queuing or submitting
#   e-reporting data.
#   ``directory_registration`` advertises managing the company's own directory
#   entries (Peppol / PPF). Only SuperPDP exposes these endpoints; CDAR platforms
#   register the company through their own portal.
PLATFORM_CAPABILITIES = {
	"SuperPDP": {"self_provision": False, "ereporting": True, "directory_registration": True},
	"Esalink": {"self_provision": False, "ereporting": False, "directory_registration": False},
	"Custom": {"self_provision": False, "ereporting": False, "directory_registration": False},
}


def platform_supports(platform_type: str, capability: str) -> bool:
	"""True if the given platform type advertises the named capability."""
	return bool(PLATFORM_CAPABILITIES.get(platform_type, {}).get(capability))


@frappe.whitelist()
def get_platform_capabilities() -> dict:
	"""Expose PLATFORM_CAPABILITIES to the client (registration dialog)."""
	return PLATFORM_CAPABILITIES


def _build_client(
	platform_type,
	client_id,
	client_secret,
	api_base_url=None,
	platform_code=None,
	sandbox=False,
	auth_method="client_credentials",
	platform_name=None,
):
	"""Instantiate the right PA client from raw credentials.

	Construction performs authentication (OAuth for SuperPDP/AFNOR, a token call
	for Esalink), so a successful build doubles as a connection probe.
	``sandbox`` flags a pré-production platform; only SuperPDP acts on it (skips
	pre-validation on invoice sends). ``auth_method`` selects SuperPDP's OAuth
	grant; ``authorization_code`` loads the stored refresh token. Raises on failure.
	"""
	if platform_type == "SuperPDP":
		from etransactions.components.superpdp import SuperPDPClient
		if auth_method == "authorization_code":
			tok = _get_platform_token(platform_name) if platform_name else {}
			return SuperPDPClient(
				client_id,
				client_secret,
				base_url=api_base_url or None,
				disable_pre_check=sandbox,
				auth_method="authorization_code",
				refresh_token=tok.get("refresh_token"),
				on_token_refreshed=(
					(lambda data: _store_platform_token(platform_name, data)) if platform_name else None
				),
			)
		return SuperPDPClient(client_id, client_secret, base_url=api_base_url or None, disable_pre_check=sandbox)

	if platform_type == "Custom":
		from etransactions.components.afnor import AFNORClient
		return AFNORClient(client_id, client_secret, base_url=api_base_url or "")

	# Esalink (HUBTIMIZE) — native AFNOR-style client with the hubtimize-api-key header.
	# Credentials are the company's minted clientId/clientSecret; the api-key and base
	# URL are environment-level and read from eTransactions Settings.
	from etransactions.components.esalink import EsalinkClient, base_url_for_environment
	from etransactions.plateforme_agreee.esalink_provisioning import esalink_runtime_config

	cfg = esalink_runtime_config()
	base = api_base_url or base_url_for_environment(cfg["environment"])
	return EsalinkClient(
		username=client_id,
		password=client_secret,
		api_key=cfg["api_key"],
		base_url=base,
	)


def get_platform_for_context(company: str, customer: str = None, transaction_type: str = "sales"):
	"""Resolve the eTransactions Accredited Platform for a given context.

	Platform resolution order:
	1. Customer-specific override (if customer is provided)
	2. Customer Group override (if customer is provided)
	3. Active company platform matching the transaction type

	transaction_type: "sales" or "purchases"
	Returns the platform name (str) or None if no platform is configured.
	"""
	if customer:
		customer_platform = frappe.db.get_value("Customer", customer, "accredited_platform_override")
		if customer_platform:
			return customer_platform

		customer_group = frappe.db.get_value("Customer", customer, "customer_group")
		if customer_group:
			group_platform = frappe.db.get_value("Customer Group", customer_group, "accredited_platform_override")
			if group_platform:
				return group_platform

	if transaction_type == "sales":
		type_filter = ["Sales", "Both"]
	elif transaction_type == "purchases":
		type_filter = ["Purchases", "Both"]
	else:
		type_filter = ["Sales", "Purchases", "Both"]

	return frappe.db.get_value(
		"eTransactions Accredited Platform",
		{"company": company, "is_active": 1, "transaction_type": ["in", type_filter]},
		"name",
		order_by="creation asc",
	)


def get_platform_for_company(company: str, transaction_type: str = "sales"):
	"""Return the first active eTransactions Accredited Platform doc for the given company."""
	platform_name = get_platform_for_context(company, transaction_type=transaction_type)
	if platform_name:
		return frappe.get_cached_doc("eTransactions Accredited Platform", platform_name)
	return None


def get_platform_settings(company: str, transaction_type: str = "sales"):
	"""Kept for backward compatibility. Use get_platform_for_company() instead."""
	return get_platform_for_company(company, transaction_type=transaction_type)


def get_client(company: str, customer: str = None, transaction_type: str = "sales"):
	"""Return an authenticated PA client for the given company.

	Returns a SuperPDPClient, AFNORClient, or EsalinkClient depending on the
	configured platform type.  All implement the same interface:
	submit_invoice, get_invoice_status, list_incoming_invoices,
	download_flow, get_directory_for_siren.

	Raises frappe.ValidationError if no platform is configured or auth fails.
	"""
	platform_name = get_platform_for_context(company, customer=customer, transaction_type=transaction_type)
	if not platform_name:
		frappe.throw(
			_("No eTransactions Accredited Platform configured for company {0}. Configure it in eTransactions Settings.").format(company)
		)

	platform_doc = frappe.get_cached_doc("eTransactions Accredited Platform", platform_name)
	try:
		return _build_client(
			platform_doc.platform_type,
			platform_doc.get_password("client_id"),
			platform_doc.get_password("client_secret", raise_exception=False),
			api_base_url=platform_doc.api_base_url,
			platform_code=platform_doc.platform_code,
			sandbox=bool(platform_doc.is_sandbox),
			auth_method=platform_doc.get("auth_method") or "client_credentials",
			platform_name=platform_name,
		)
	except Exception as e:
		frappe.throw(
			_("Failed to connect to eTransactions Accredited Platform for company {0}: {1}").format(
				company, str(e)
			)
		)


def get_session(company: str, customer: str = None, transaction_type: str = "sales"):
	"""Deprecated. Use :func:`get_client`, which returns a unified client for every
	platform type (Esalink, SuperPDP, Custom AFNOR).

	Esalink no longer exposes a raw pyfrctc session — it is now a native HTTP client —
	so this accessor only raises and points callers at get_client().
	"""
	frappe.throw(
		_("get_session() is no longer supported. Use get_client() instead — it returns a unified client for all platforms.")
	)


# ---------------------------------------------------------------------------
# Connection health
# ---------------------------------------------------------------------------


@frappe.whitelist()
def test_platform_credentials(
	platform_type,
	client_id,
	client_secret,
	api_base_url=None,
	platform_code=None,
	auth_method=None,
	platform_name=None,
):
	"""Probe credentials without persisting anything (used before saving a platform).

	Returns ``{"status": "ok"|"error", "message": str}`` — never raises, so the
	dialog can render the outcome inline.
	"""
	frappe.only_for(("System Manager", "Accounts Manager"))
	if not auth_method and platform_name and frappe.db.exists("eTransactions Accredited Platform", platform_name):
		auth_method = frappe.db.get_value("eTransactions Accredited Platform", platform_name, "auth_method")
	auth_method = auth_method or "client_credentials"
	if auth_method == "authorization_code":
		if not (platform_name and _get_platform_token(platform_name).get("refresh_token")):
			return {
				"status": "error",
				"message": _(
					"This platform uses interactive onboarding: save it, then run"
					" \"Connect account (onboarding)\" to obtain tokens before testing."
				),
			}
	try:
		client = _build_client(
			platform_type,
			client_id,
			client_secret,
			api_base_url,
			platform_code,
			auth_method=auth_method,
			platform_name=platform_name,
		)
		client.healthcheck()
		return {"status": "ok", "message": _("Connection successful.")}
	except Exception as e:
		return {"status": "error", "message": str(e)}


def check_platform_health(platform_name: str, store: bool = True) -> dict:
	"""Probe a saved platform's connection and (by default) persist the outcome."""
	doc = frappe.get_cached_doc("eTransactions Accredited Platform", platform_name)
	try:
		client = _build_client(
			doc.platform_type,
			doc.get_password("client_id"),
			doc.get_password("client_secret", raise_exception=False),
			api_base_url=doc.api_base_url,
			platform_code=doc.platform_code,
			auth_method=doc.get("auth_method") or "client_credentials",
			platform_name=platform_name,
		)
		client.healthcheck()
		status, message = "ok", _("Connection successful.")
	except Exception as e:
		status, message = "error", str(e)

	if store:
		frappe.db.set_value(
			"eTransactions Accredited Platform",
			platform_name,
			{
				"last_health_status": status,
				"last_health_check": now_datetime(),
				"last_health_message": message[:140],
			},
			update_modified=False,
		)
	return {"status": status, "message": message}


@frappe.whitelist()
def run_platform_health_check(platform_name: str) -> dict:
	"""Whitelisted: probe one saved platform now and store the result."""
	frappe.only_for(("System Manager", "Accounts Manager"))
	result = check_platform_health(platform_name)
	frappe.db.commit()
	return result


def run_all_health_checks():
	"""Daily scheduler: refresh the connection health of every active platform."""
	for name in frappe.get_all(
		"eTransactions Accredited Platform", filters={"is_active": 1}, pluck="name"
	):
		try:
			check_platform_health(name)
			frappe.db.commit()
		except Exception:
			frappe.db.rollback()
			frappe.log_error(frappe.get_traceback(), f"PA health check failed: {name}")


# ---------------------------------------------------------------------------
# Interactive OAuth2 onboarding (authorization_code + PKCE) for SuperPDP
# ---------------------------------------------------------------------------

_OAUTH_STATE_TTL = 600  # seconds the onboarding state stays valid


def _oauth_redirect_uri() -> str:
	"""The redirect URI registered in the platform's portal (matches the form JS)."""
	return f"{frappe.utils.get_url()}/api/method/etransactions.plateforme_agreee.session.oauth_callback"


def _get_platform_token(platform_name: str) -> dict:
	"""Return the stored, decrypted token set for a platform (empty if none)."""
	name = frappe.db.get_value("eTransactions Platform Token", {"platform": platform_name})
	if not name:
		return {}
	doc = frappe.get_doc("eTransactions Platform Token", name)
	return {
		"access_token": doc.get_password("access_token", raise_exception=False),
		"refresh_token": doc.get_password("refresh_token", raise_exception=False),
		"expires_at": doc.expires_at,
	}


def _store_platform_token(platform_name: str, token: dict) -> None:
	"""Persist a token set on its own record (encrypted Password fields).

	Keeping tokens off the platform doc avoids write contention with the frequent
	reads/writes there. Only overwrites the refresh token when the platform rotated
	it, so a plain access-token refresh keeps the existing refresh token.
	"""
	name = frappe.db.get_value("eTransactions Platform Token", {"platform": platform_name})
	doc = (
		frappe.get_doc("eTransactions Platform Token", name)
		if name
		else frappe.new_doc("eTransactions Platform Token")
	)
	if not name:
		doc.platform = platform_name
	doc.access_token = token.get("access_token")
	if token.get("refresh_token"):
		doc.refresh_token = token.get("refresh_token")
	doc.expires_at = frappe.utils.add_to_date(
		frappe.utils.now_datetime(), seconds=int(token.get("expires_in", 3600))
	)
	doc.flags.ignore_permissions = True
	doc.save()


@frappe.whitelist()
def start_oauth_onboarding(platform_name: str) -> dict:
	"""Begin the SuperPDP authorization_code onboarding; return the authorize URL.

	Generates a PKCE pair + anti-CSRF ``state``, stashes them in the server cache
	keyed by state (bound to the current user), and builds the consent URL. The
	browser then redirects to :func:`oauth_callback`.
	"""
	frappe.only_for(("System Manager", "Accounts Manager"))
	doc = frappe.get_cached_doc("eTransactions Accredited Platform", platform_name)
	if doc.platform_type != "SuperPDP":
		frappe.throw(_("Interactive onboarding is only available for SuperPDP platforms."))

	import secrets

	from etransactions.components.superpdp import SuperPDPClient

	code_verifier, code_challenge = SuperPDPClient.generate_pkce_pair()
	state = secrets.token_urlsafe(24)
	frappe.cache().set_value(
		f"superpdp_oauth:{state}",
		{"platform": platform_name, "code_verifier": code_verifier, "user": frappe.session.user},
		expires_in_sec=_OAUTH_STATE_TTL,
	)

	siren = frappe.db.get_value("Company", doc.company, "siren_number") if doc.company else None
	url = SuperPDPClient.build_authorize_url(
		client_id=doc.get_password("client_id"),
		redirect_uri=_oauth_redirect_uri(),
		state=state,
		code_challenge=code_challenge,
		base_url=doc.api_base_url or None,
		company_number=siren,
		company_number_scheme=("sandbox" if doc.is_sandbox else "fr_siren") if siren else None,
		login_hint=frappe.session.user if "@" in (frappe.session.user or "") else None,
	)
	return {"authorize_url": url}


@frappe.whitelist()
def oauth_callback(**kwargs):
	"""Redirect target for SuperPDP onboarding: validate state, store the tokens.

	Validates the ``state`` against the cached value for the current user (CSRF),
	exchanges the authorization code for the token set, persists it, and redirects
	back to the platform form. The authorization code and tokens are never logged.
	"""
	state = kwargs.get("state")
	code = kwargs.get("code")
	cached = frappe.cache().get_value(f"superpdp_oauth:{state}") if state else None
	if not cached or cached.get("user") != frappe.session.user or not code:
		frappe.throw(_("Invalid or expired onboarding session. Please restart the onboarding."))
	frappe.cache().delete_value(f"superpdp_oauth:{state}")

	platform_name = cached["platform"]
	doc = frappe.get_cached_doc("eTransactions Accredited Platform", platform_name)

	from etransactions.components.superpdp import SuperPDPClient

	token = SuperPDPClient.exchange_authorization_code(
		client_id=doc.get_password("client_id"),
		code=code,
		code_verifier=cached["code_verifier"],
		redirect_uri=_oauth_redirect_uri(),
		base_url=doc.api_base_url or None,
	)
	_store_platform_token(platform_name, token)
	# Switch the platform to the interactive method now that a refresh token exists.
	if doc.get("auth_method") != "authorization_code":
		frappe.db.set_value("eTransactions Accredited Platform", platform_name, "auth_method", "authorization_code")

	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = f"/app/etransactions-accredited-platform/{platform_name}"
