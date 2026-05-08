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

	# Determine which transaction_type values to accept
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
	"""Return the first active eTransactions Accredited Platform for the given company and transaction type."""
	platform_name = get_platform_for_context(company, transaction_type=transaction_type)
	if platform_name:
		return frappe.get_cached_doc("eTransactions Accredited Platform", platform_name)
	return None


def get_platform_settings(company: str, transaction_type: str = "sales"):
	"""Return the eTransactions Accredited Platform document for the given company.

	Kept for backward compatibility. Defaults to sales transaction type.
	"""
	return get_platform_for_company(company, transaction_type=transaction_type)


def get_session(company: str, customer: str = None, transaction_type: str = "sales"):
	"""Return an authenticated pyfrctc OAuth session for the given company.

	Reads credentials from the eTransactions Accredited Platform document.
	Platform resolution order:
	- Customer override (if provided)
	- Customer Group override
	- Company's platform (filtered by transaction_type)
	- Global default platform

	Raises frappe.ValidationError if not configured or connection fails.
	"""
	try:
		from pyfrctc import get_session as _get_session
	except ImportError:
		frappe.throw(_("The pyfrctc library is not installed. Check your bench dependencies."))

	platform_doc = get_platform_for_company(company, transaction_type=transaction_type)
	if not platform_doc:
		frappe.throw(
			_("No eTransactions Accredited Platform configured for company {0}. Configure it in eTransactions Settings.").format(company)
		)

	platform_code = platform_doc.platform_code
	if not platform_code:
		frappe.throw(
			_("No platform code configured for company {0}. Check the eTransactions Accredited Platform settings.").format(company)
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
