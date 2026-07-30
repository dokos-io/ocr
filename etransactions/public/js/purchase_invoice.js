frappe.provide("etransactions");

frappe.ui.form.on('Purchase Invoice', {
	refresh(frm) {
		// OCR "Original Invoice" preview is a separate feature and always runs.
		etransactions.original_file_preview(frm);

		// eTransactions is opt-in per site: the e-invoicing readiness panel and
		// lifecycle actions only show when the feature is activated in settings.
		if (!frappe.boot.einvoicing_enabled) return;

		etransactions.invoiceReadiness.refresh(frm);

		if (!frm.is_new()) {
			frappe.call({
				method: "etransactions.etransactions.doctype.einvoice.einvoice.get_transaction_einvoice",
				args: { doctype: frm.doctype, name: frm.doc.name },
				callback(r) {
					if (r.message) {
						etransactions.lifecycle.attach(frm, {
							einvoice: r.message.name,
							side: r.message.side,
							pa_status: r.message.pa_status,
							group: __("eInvoicing"),
						});
					}
				},
				// The lifecycle panel is an add-on: a lookup failure must never
				// throw a traceback dialog over the invoice the user is working on.
				error: () => {},
			});
		}
	},

	supplier: (frm) => frappe.boot.einvoicing_enabled && etransactions.invoiceReadiness.refresh(frm),
	after_save: (frm) => frappe.boot.einvoicing_enabled && etransactions.invoiceReadiness.refresh(frm),
})
