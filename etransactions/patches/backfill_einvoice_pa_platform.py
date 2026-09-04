import frappe

from etransactions.plateforme_agreee.session import get_platform_for_context


def execute():
	"""Backfill pa_platform/pa_platform_name on PA-received eInvoices created before the
	"show the receiving PA as a pill" feature started stamping them at creation time.

	Historical eInvoices don't record which platform record actually delivered them, only
	their company — infer it from the company's *currently* active purchases platform.
	Safe today since no company on this site has ever had more than one PA configured; if a
	company later has more than one over time, older backfilled records could be mislabelled.
	"""
	if not frappe.db.table_exists("eInvoice"):
		return

	einvoices = frappe.get_all(
		"eInvoice",
		filters={
			"einvoice_type": "Incoming",
			"pa_flow_id": ("is", "set"),
			"pa_platform_name": ("in", ("", None)),
		},
		fields=["name", "company"],
	)
	if not einvoices:
		return

	platform_cache = {}

	for einvoice in einvoices:
		if einvoice.company not in platform_cache:
			platform_cache[einvoice.company] = get_platform_for_context(
				einvoice.company, transaction_type="purchases"
			)
		platform = platform_cache[einvoice.company]
		if not platform:
			continue

		platform_name = frappe.db.get_value("eTransactions Accredited Platform", platform, "platform_name")
		if not platform_name:
			continue

		try:
			frappe.db.set_value(
				"eInvoice",
				einvoice.name,
				{"pa_platform": platform, "pa_platform_name": platform_name},
				update_modified=False,
			)
			frappe.db.set_value(
				"Supplier Invoice",
				{"einvoice": einvoice.name},
				"pa_platform_name",
				platform_name,
				update_modified=False,
			)
		except Exception:
			continue
