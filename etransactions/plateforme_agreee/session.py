import frappe
from frappe import _


def get_platform_for_context(company: str, customer: str = None, transaction_type: str = "sales"):
	"""Resolve the eTransactions Accredited Platform for a given context.

	Platform resolution order:
	1. Customer-specific override (if customer is provided)
	2. Customer Group override (if customer is provided)
	3. Active company platform matching the transaction type
	4. Global default from eTransactions Settings for that transaction type

	transaction_type: "sales" or "purchases"
	Returns the platform name (str) or None if no platform is configured.
	"""
	settings = frappe.get_cached_doc("eTransactions Settings")

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

	platform = frappe.db.get_value(
		"eTransactions Accredited Platform",
		{"company": company, "is_active": 1, "transaction_type": ["in", type_filter]},
		"name",
		order_by="creation asc",
	)

	if platform:
		return platform

	if transaction_type == "sales":
		return settings.default_sales_platform
	elif transaction_type == "purchases":
		return settings.default_purchases_platform
	return settings.default_sales_platform or settings.default_purchases_platform


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
	client_id = platform_doc.get_password("client_id")
	client_secret = platform_doc.get_password("client_secret")

	if platform_doc.platform_type == "SuperPDP":
		from etransactions.components.superpdp import SuperPDPClient
		base_url = platform_doc.api_base_url or None
		try:
			return SuperPDPClient(client_id, client_secret, base_url=base_url)
		except Exception as e:
			frappe.throw(
				_("Failed to initialise SuperPDP client for company {0}: {1}").format(company, str(e))
			)

	if platform_doc.platform_type == "Custom":
		from etransactions.components.afnor import AFNORClient
		try:
			return AFNORClient(client_id, client_secret, base_url=platform_doc.api_base_url or "")
		except Exception as e:
			frappe.throw(
				_("Failed to initialise AFNOR client for company {0}: {1}").format(company, str(e))
			)

	# Esalink — use pyfrctc
	try:
		from pyfrctc import get_session as _get_session
	except ImportError:
		frappe.throw(_("The pyfrctc library is not installed. Check your bench dependencies."))

	platform_code = platform_doc.platform_code
	if not platform_code:
		frappe.throw(
			_("No platform code configured for company {0}. Check the eTransactions Accredited Platform settings.").format(company)
		)

	from etransactions.plateforme_agreee.esalink import ESALINKClient
	try:
		session = _get_session(client_id, client_secret, platform=platform_code)
		return ESALINKClient(session)
	except Exception as e:
		frappe.throw(
			_("Failed to connect to eTransactions Accredited Platform ({0}) for company {1}: {2}").format(
				platform_code, company, str(e)
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
