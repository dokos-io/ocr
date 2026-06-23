// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("Customer", {
	refresh(frm) {
		if (frm.fields_dict.etransactions_wizard_html && etransactions.EinvoiceReadinessIndicator) {
			frm._et_readiness = frm._et_readiness || new etransactions.EinvoiceReadinessIndicator(frm);
			frm._et_readiness.refresh();
		}

		// Scope the default routing line to this customer's own directory lines.
		frm.set_query("default_directory_line", () => ({ filters: { customer: frm.doc.name } }));

		// Offer only CEF EAS schemes — anything else fails EN16931 (BR-CL-25).
		frm.set_query("etransactions_electronic_address_scheme", () => ({
			query: "etransactions.overrides.master_data.eas_scheme_query",
		}));

		if (!frm.is_new()) {
			frm.add_custom_button(__("Sync Directory Lines"), () => {
				frappe.db
					.get_list("eTransactions Accredited Platform", {
						filters: { is_active: 1 },
						fields: ["company"],
						group_by: "company",
					})
					.then((rows) => {
						const companies = [...new Set(rows.map((r) => r.company))];
						if (companies.length <= 1) {
							_do_sync(frm, companies[0] || null);
						} else {
							frappe.prompt(
								{
									label: __("Company"),
									fieldname: "company",
									fieldtype: "Link",
									options: "Company",
									default: companies[0],
									reqd: 1,
								},
								({ company }) => _do_sync(frm, company),
								__("Select Company"),
								__("Sync"),
							);
						}
					});
			}, __("Accredited Platform"));
		}
	},
});

function _do_sync(frm, company) {
	frappe.call({
		method: "etransactions.plateforme_agreee.directory.sync_customer_directory",
		args: { customer: frm.doc.name, company },
		freeze: true,
		freeze_message: __("Syncing directory lines…"),
		callback() {
			frm.reload_doc();
		},
	});
}
