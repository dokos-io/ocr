frappe.provide("etransactions");

frappe.ui.form.on('Purchase Invoice', {
	refresh(frm) {
		etransactions.original_file_preview(frm);
	},
})