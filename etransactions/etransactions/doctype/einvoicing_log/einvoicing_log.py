import frappe
from frappe.model.document import Document

DEFAULT_LOG_VACUUM_DAYS = 600


class eInvoicingLog(Document):
	@staticmethod
	def create_log(result: dict):
		"""Create an eInvoicing Log record from a result dict."""
		logs = []
		has_error = False
		has_warning = False

		for log_type, msg in result.get("logs", []):
			if log_type == "error":
				logs.append(f'<span style="color:red;font-weight:bold">ERROR </span>{msg}')
				has_error = True
			elif log_type == "warning":
				logs.append(f'<span style="color:orange;font-weight:bold">WARNING </span>{msg}')
				has_warning = True
			else:
				logs.append(f'<span style="color:green;font-weight:bold">INFO </span>{msg}')

		if has_error:
			status = "failure"
		elif has_warning:
			status = "success_warn"
		else:
			status = "success"

		frappe.get_doc({
			"doctype": "eInvoicing Log",
			"company": result.get("company"),
			"operation_type": result.get("operation_type"),
			"origin": result.get("origin"),
			"status": status,
			"new_count": result.get("new_count", 0),
			"updated_count": result.get("updated_count", 0),
			"logs": "<br>".join(logs),
		}).insert(ignore_permissions=True)


def vacuum_old_logs():
	"""Delete eInvoicing Log records older than the configured retention period."""
	days = DEFAULT_LOG_VACUUM_DAYS
	# Use the longest directory_refresh_days from any active platform as a multiplier
	max_refresh = frappe.db.get_value(
		"eTransactions Accredited Platform",
		{"is_active": 1},
		"max(directory_refresh_days)",
	)
	if max_refresh:
		days = max(days, int(max_refresh) * 40)

	cutoff = frappe.utils.add_days(frappe.utils.nowdate(), -days)
	frappe.db.delete("eInvoicing Log", {"creation": ("<", cutoff)})
