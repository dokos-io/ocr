// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("Supplier", {
	refresh(frm) {
		if (frm.fields_dict.etransactions_wizard_html && etransactions.EinvoiceReadinessWizard) {
			frm._et_wizard = frm._et_wizard || new etransactions.EinvoiceReadinessWizard(frm);
			frm._et_wizard.refresh();
		}
	},
});
