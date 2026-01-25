// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("Supplier Invoices Basket", {
	refresh(frm) {
		new etransactions.DocumentAnalyzer(frm)

		if (!frm.is_new() && !frm.__islocal && frm.doc.status == "Not Started") {
			frm.page.set_primary_action(__('Create purchase invoices'), function() {
				trigger_request_creation(frm);
			});
		}

		if (!frm.__islocal && frm.doc.status != "Not Started") {
			frm.page.clear_primary_action()
		}

		if (!frm.__islocal && frm.doc.status == "Closed") {
			frm.add_custom_button(__("Re-open"), () => {
				frm.set_value("status", "Not Started")
				frm.save()
			})
		}
	},
});


const trigger_request_creation = (frm) => {
	frappe.show_alert({
		indicator: "orange",
		message: __("Request creation in progress")
	})
	frm.page.clear_primary_action()

	frappe.call({
		method: "route_invoices",
		doc: frm.doc
	}).then(() => {
		frm.reload_doc()
		frappe.show_alert({
			indicator: "orange",
			message: __("Extraction in progress")
		})
	})
}