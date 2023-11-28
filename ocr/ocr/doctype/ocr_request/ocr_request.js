// Copyright (c) 2023, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("OCR Request", {
	refresh(frm) {
		if (frm.doc.status == "Analysis Completed") {
			frm.page.set_primary_action(__('Create purchase invoice'), function() {
				frappe.call({
					method: "create_purchase_invoice",
					doc: frm.doc
				}).then(() => {
					frm.reload_doc()
					frappe.show_alert({
						indicator: "green",
						message: __("Purchase invoice created")
					})
				})
			})
		}
	},
});
