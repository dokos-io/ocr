frappe.listview_settings["OCR Request"] = {
	hide_name_column: 1,
	button: {
		show(doc) {
			return (doc.transaction_type && doc.status == "Transaction Matched");
		},
		get_label() {
			return frappe.utils.icon("link-url", "sm");
		},
		get_description(doc) {
			return __("View {0}", [__(doc.transaction_type)]);
		},
		action(doc) {
			frappe.db.get_value(doc.transaction_type, {"ocr_request": doc.name}, "name", r => {
				if (r.name) {
					frappe.set_route("Form", doc.transaction_type, r.name);
				} else {
					frappe.show_alert({
						indicator: "red",
						message: __("Transaction could not be found")
					})
				}
			})
		},
	},
};
