frappe.provide("etransactions");

frappe.ui.form.on('Purchase Invoice', {
	refresh(frm) {
		etransactions.original_file_preview(frm);
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
						});
					}
				},
			});
		}
	},

	supplier: (frm) => etransactions.invoiceReadiness.refresh(frm),
	after_save: (frm) => etransactions.invoiceReadiness.refresh(frm),
})
