import frappe


def execute():
	"""Remove the orphaned "Accounting Hub" Module Def after the rename to "eTransactions Hub".

	App modules cannot be renamed in place (Module Def.before_rename only allows custom
	modules), so model sync creates the new "eTransactions Hub" Module Def from modules.txt
	and re-points the doctypes via their JSON. This post-sync patch deletes the leftover
	"Accounting Hub" Module Def once nothing references it anymore.
	"""
	if not frappe.db.exists("Module Def", "Accounting Hub"):
		return

	# Safety: only delete once no doctype still points at the old module.
	if frappe.db.exists("DocType", {"module": "Accounting Hub"}):
		return

	frappe.delete_doc("Module Def", "Accounting Hub", force=True, ignore_permissions=True)
