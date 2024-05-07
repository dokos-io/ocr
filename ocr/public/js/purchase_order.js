frappe.provide("ocr");

frappe.ui.form.on('Purchase Order', {
	refresh(frm) {
		ocr.original_file_preview(frm);
	},
})