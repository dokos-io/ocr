frappe.listview_settings["Expense"] = {
	onload: function (doclist) {
		doclist.page.add_action_item(__("Add Receipts"), () => {
			console.log("Hello")
		}, false);
	}
}