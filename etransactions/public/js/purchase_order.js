frappe.provide("etransactions");

const _existing_listview = frappe.listview_settings["Purchase Order"] || {};
const _existing_refresh = _existing_listview.refresh;

frappe.ui.form.on('Purchase Order', {
	refresh(frm) {
		if (_existing_refresh) {
			_existing_refresh.call(this, listview);
		}

		etransactions.original_file_preview(frm);
	},
})