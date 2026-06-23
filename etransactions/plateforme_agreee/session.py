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
PLATFORM_CAPABILITIES = {
	"SuperPDP": {"self_provision": False, "ereporting": True},
	"Esalink": {"self_provision": False, "ereporting": False},
	"Custom": {"self_provision": False, "ereporting": False},
}


def platform_supports(platform_type: str, capability: str) -> bool:
	"""True if the given platform type advertises the named capability."""
	return bool(PLATFORM_CAPABILITIES.get(platform_type, {}).get(capability))


@frappe.whitelist()
def get_platform_capabilities() -> dict:
	"""Expose PLATFORM_CAPABILITIES to the client (registration dialog)."""
	return PLATFORM_CAPABILITIES


def _build_client(platform_type, client_id, client_secret, api_base_url=None, platform_code=None, sandbox=False):
	"""Instantiate the right PA client from raw credentials.

	Construction performs authentication (OAuth for SuperPDP/AFNOR, a pyfrctc
	session for Esalink), so a successful build doubles as a connection probe.
	``sandbox`` flags a pré-production platform; only SuperPDP acts on it (skips
	pre-validation on invoice sends). Raises on failure.
	"""
	if platform_type == "SuperPDP":
		from etransactions.components.superpdp import SuperPDPClient
		return SuperPDPClient(client_id, client_secret, base_url=api_base_url or None, disable_pre_check=sandbox)

	if platform_type == "Custom":
		from etransactions.components.afnor import AFNORClient
		return AFNORClient(client_id, client_secret, base_url=api_base_url or "")

	# Esalink — pyfrctc session
	try:
		from pyfrctc import get_session as _get_session
	except ImportError:
		frappe.throw(_("The pyfrctc library is not installed. Check your bench dependencies."))
	if not platform_code:
		frappe.throw(_("No platform code configured for this Esalink platform."))
	from etransactions.plateforme_agreee.esalink import ESALINKClient
	return ESALINKClient(_get_session(client_id, client_secret, platform=platform_code))


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

	Returns a SuperPDPClient, AFNORClient, or ESALINKClient depending on the
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
			platform_doc.get_password("client_secret"),
			api_base_url=platform_doc.api_base_url,
			platform_code=platform_doc.platform_code,
			sandbox=bool(platform_doc.is_sandbox),
		)
	except Exception as e:
		frappe.throw(
			_("Failed to connect to eTransactions Accredited Platform for company {0}: {1}").format(
				company, str(e)
			)
		)


def get_session(company: str, customer: str = None, transaction_type: str = "sales"):
	"""Return a raw pyfrctc session. Kept for backward compatibility.

	Prefer get_client() for new code — it works for both Esalink and SuperPDP.
	Raises frappe.ValidationError for SuperPDP platforms (no pyfrctc session).
	"""
	platform_name = get_platform_for_context(company, customer=customer, transaction_type=transaction_type)
	if not platform_name:
		frappe.throw(
			_("No eTransactions Accredited Platform configured for company {0}.").format(company)
		)

	platform_doc = frappe.get_cached_doc("eTransactions Accredited Platform", platform_name)

	if platform_doc.platform_type == "SuperPDP":
		frappe.throw(
			_("get_session() is not supported for SuperPDP platforms. Use get_client() instead.")
		)

	try:
		from pyfrctc import get_session as _get_session
	except ImportError:
		frappe.throw(_("The pyfrctc library is not installed. Check your bench dependencies."))

	platform_code = platform_doc.platform_code
	if not platform_code:
		frappe.throw(
			_("No platform code configured for company {0}.").format(company)
		)

	client_id = platform_doc.get_password("client_id")
	client_secret = platform_doc.get_password("client_secret")
	try:
		return _get_session(client_id, client_secret, platform=platform_code)
	except Exception as e:
		frappe.throw(
			_("Failed to connect to eTransactions Accredited Platform ({0}) for company {1}: {2}").format(
				platform_code, company, str(e)
			)
		)


# ---------------------------------------------------------------------------
# Connection health
# ---------------------------------------------------------------------------


@frappe.whitelist()
def test_platform_credentials(platform_type, client_id, client_secret, api_base_url=None, platform_code=None):
	"""Probe credentials without persisting anything (used before saving a platform).

	Returns ``{"status": "ok"|"error", "message": str}`` — never raises, so the
	dialog can render the outcome inline.
	"""
	frappe.only_for(("System Manager", "Accounts Manager"))
	try:
		client = _build_client(platform_type, client_id, client_secret, api_base_url, platform_code)
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
			doc.get_password("client_secret"),
			api_base_url=doc.api_base_url,
			platform_code=doc.platform_code,
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
