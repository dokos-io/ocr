frappe.provide("ocr");

frappe.ui.form.on('Purchase Invoice', {
	refresh(frm) {
		new ocr.DocumentAnalyzer(frm)
	}
})