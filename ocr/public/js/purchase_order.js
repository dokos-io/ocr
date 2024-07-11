frappe.provide("ocr");

frappe.ui.form.on('Purchase Order', {
	refresh(frm) {
		ocr.original_file_preview(frm);
	},

	after_save: function (frm) {
		if (frm.doc.docstatus == 1 ) {
			frappe.run_serially([
				() => frappe.timeout(1),
				() => {
					if (frm.doc.ocr_request) {
						frappe.set_route("Form", "OCR Request", frm.doc.ocr_request);
					}
				},
			]);
		}
	},
})