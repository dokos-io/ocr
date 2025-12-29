frappe.provide("etransactions");

frappe.ui.form.on('Purchase Order', {
	refresh(frm) {
		etransactions.original_file_preview(frm);
	},
})