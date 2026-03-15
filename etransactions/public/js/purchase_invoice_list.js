const _existing_listview = frappe.listview_settings["Purchase Invoice"] || {};
const _existing_onload = _existing_listview.onload;

frappe.listview_settings["Purchase Invoice"] = Object.assign(_existing_listview, {
	onload(listview) {
		if (_existing_onload) {
			_existing_onload.call(this, listview);
		}

		listview.page.set_secondary_action(__("Upload a supplier invoice"), () => {
			frappe.set_route("List", "Supplier Invoice");
		});
	},
});
