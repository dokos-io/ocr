frappe.provide("etransactions");

frappe.ui.form.on('Purchase Invoice', {
	refresh(frm) {
		// OCR "Original Invoice" preview is a separate feature and always runs.
		etransactions.original_file_preview(frm);

		// eTransactions is opt-in per site: the e-invoicing readiness panel and
		// lifecycle actions only show when the feature is activated in settings.
		if (!frappe.boot.einvoicing_enabled) return;

		etransactions.invoiceReadiness.refresh(frm);
		etransactions.lifecycle.attach_for_transaction(frm);
	},

	supplier: (frm) => frappe.boot.einvoicing_enabled && etransactions.invoiceReadiness.refresh(frm),
	after_save: (frm) => frappe.boot.einvoicing_enabled && etransactions.invoiceReadiness.refresh(frm),
})
