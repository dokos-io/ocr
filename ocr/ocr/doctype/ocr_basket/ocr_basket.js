// Copyright (c) 2023, Dokos SAS and contributors
// For license information, please see license.txt

frappe.provide("ocr")

frappe.ui.form.on("OCR Basket", {
	refresh(frm) {
		new ocr.DocumentAnalyzer(frm)

		if (frm.doc.status == "Not Started") {
			const action_title = frm.doc.document_type == 'Purchase Invoice' ? 'Create purchase invoices' : 'Create expenses'
			frm.page.add_action_item(__(action_title), function() {
				frappe.show_alert({
					indicator: "orange",
					message: __("Request creation in progress")
				})
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
	},
});
