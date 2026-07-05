// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("Supplier", {
	refresh(frm) {
		// eTransactions is opt-in per site: nothing e-invoicing shows unless the
		// feature is activated in eTransactions Settings.
		if (!frappe.boot.einvoicing_enabled) return;

		if (frm.fields_dict.etransactions_wizard_html && etransactions.EinvoiceReadinessIndicator) {
			frm._et_readiness = frm._et_readiness || new etransactions.EinvoiceReadinessIndicator(frm);
			frm._et_readiness.refresh();
		}

		// Pappers (ERPNext France) does the same French company lookup; only offer SIRENE
		// when Pappers is not enabled, to avoid two redundant autofill entry points.
		if (etransactions.sirene && !frappe.boot.pappers_enabled) {
			frm.add_custom_button(__("Fill from SIRENE"), () => etransactions.sirene.open(frm), __("eInvoicing"));
		}
	},
});
