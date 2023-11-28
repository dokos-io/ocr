// Copyright (c) 2023, Dokos SAS and contributors
// For license information, please see license.txt

frappe.provide("ocr")

frappe.ui.form.on("OCR Purchase Invoice Basket", {
	refresh(frm) {
		new ocr.DocumentAnalyzer(frm)

		if (!frm.is_new() && !frm.__islocal && frm.doc.status == "Not Started") {
			frm.page.set_primary_action(__('Create purchase invoices'), function() {
				frappe.show_alert({
					indicator: "orange",
					message: __("Request creation in progress")
				})
				frm.page.clear_primary_action()

				frappe.call({
					method: "create_requests",
					doc: frm.doc
				}).then(() => {
					frm.reload_doc()
					frappe.show_alert({
						indicator: "orange",
						message: __("Extraction in progress")
					})
				})
			});
		}

		if (!frm.__islocal && frm.doc.status != "Not Started") {
			frm.page.clear_primary_action()
		}
	},
});
