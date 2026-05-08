// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("Customer", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Sync Directory Lines"), () => {
				frappe.call({
					method: "etransactions.plateforme_agreee.directory.sync_customer_directory",
					args: { customer: frm.doc.name },
					freeze: true,
					freeze_message: __("Syncing directory lines…"),
					callback() {
						frm.reload_doc();
					},
				});
			}, __("Plateforme Agréée"));
		}
	},
});
