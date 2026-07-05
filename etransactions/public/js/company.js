// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("Company", {
	refresh(frm) {
		// eTransactions is opt-in per site: nothing e-invoicing shows unless the
		// feature is activated in eTransactions Settings.
		if (!frappe.boot.einvoicing_enabled) return;

		// Offer only CEF EAS schemes — anything else fails EN16931 (BR-CL-25).
		frm.set_query("etransactions_electronic_address_scheme", () => ({
			query: "etransactions.overrides.master_data.eas_scheme_query",
		}));

		if (etransactions.sirene) {
			frm.add_custom_button(__("Fill from SIRENE"), () => etransactions.sirene.open(frm), __("eInvoicing"));
		}
	},
});
