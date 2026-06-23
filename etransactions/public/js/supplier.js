// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("Supplier", {
	refresh(frm) {
		if (frm.fields_dict.etransactions_wizard_html && etransactions.EinvoiceReadinessIndicator) {
			frm._et_readiness = frm._et_readiness || new etransactions.EinvoiceReadinessIndicator(frm);
			frm._et_readiness.refresh();
		}
	},
});
