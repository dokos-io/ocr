frappe.provide("ocr");

frappe.ui.form.on('Purchase Order', {
	refresh(frm) {
		ocr.original_file_preview(frm);
	},

	after_save: function (frm) {
		frappe.db.get_single_value("OCR Settings", "do_not_create_purchase_invoices").then(r => {
			if (!r.do_not_create_purchase_invoices && frm.doc.docstatus == 1 && frm.doc.per_billed < 100.0) {
				frappe.run_serially([
					() => frappe.timeout(1),
					() => {
						if (frm.doc.ocr_request) {
							frappe.set_route("Form", "OCR Request", frm.doc.ocr_request);
						}
					},
				]);
			}
		})
	},
})