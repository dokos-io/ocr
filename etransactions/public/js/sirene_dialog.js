// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt
//
// "Fill from SIRENE" — search the French company registry by name or SIREN and
// autofill the party's identity (SIREN, VAT, legal name) plus its primary
// address (SIRET, street, city). Shared by Customer, Supplier and Company.

frappe.provide("etransactions");

etransactions.sirene = {
	open(frm) {
		const d = new frappe.ui.Dialog({
			title: __("Fill from SIRENE"),
			size: "large",
			fields: [
				{
					fieldtype: "Data",
					fieldname: "query",
					label: __("Company name or SIREN"),
					description: __("Searches the French company registry (recherche-entreprises.api.gouv.fr)"),
				},
				{ fieldtype: "HTML", fieldname: "results_html" },
			],
		});

		const $results = () => d.fields_dict.results_html.$wrapper;
		const search = frappe.utils.debounce(() => {
			const query = (d.get_value("query") || "").trim();
			if (query.length < 3) {
				$results().empty();
				return;
			}
			$results().html(
				`<div class="text-muted small">${frappe.utils.icon("loading-indicator")} ${__("Searching…")}</div>`
			);
			frappe
				.xcall("etransactions.utils.sirene.search", { query })
				.then((rows) => this._render(frm, d, rows || []))
				.catch(() => $results().html(`<div class="text-muted">${__("Search failed.")}</div>`));
		}, 400);

		d.fields_dict.query.$input.on("input", search);
		d.show();

		// Pre-fill with the current name to get instant results.
		const seed =
			frm.doc.siren_number ||
			frm.doc.customer_name ||
			frm.doc.supplier_name ||
			frm.doc.company_name;
		if (seed && !frm.is_new()) {
			d.set_value("query", seed);
			search();
		}
	},

	_render(frm, d, rows) {
		const $wrap = d.fields_dict.results_html.$wrapper.empty();
		if (!rows.length) {
			$wrap.html(`<div class="text-muted">${__("No match found.")}</div>`);
			return;
		}
		const $list = $('<div class="sirene-results"></div>').appendTo($wrap);
		rows.forEach((row) => {
			const badge = row.active
				? ""
				: ` <span class="indicator-pill red">${__("Closed")}</span>`;
			const address = [row.address_line1, row.pincode, row.city].filter(Boolean).join(", ");
			const $row = $(`
				<div class="sirene-result" style="display:flex;justify-content:space-between;gap:8px;
						padding:8px;border-bottom:1px solid var(--border-color);align-items:center">
					<div>
						<div><b>${frappe.utils.escape_html(row.name || "")}</b>${badge}</div>
						<div class="text-muted small">
							${__("SIREN")} ${frappe.utils.escape_html(row.siren || "")}
							${row.siret ? " — " + __("SIRET (head office)") + " " + frappe.utils.escape_html(row.siret) : ""}
						</div>
						<div class="text-muted small">${frappe.utils.escape_html(address)}</div>
					</div>
					<button class="btn btn-xs btn-primary">${__("Use")}</button>
				</div>`);
			$row.find("button").on("click", () => {
				d.hide();
				this._apply(frm, row);
			});
			$list.append($row);
		});
	},

	_apply(frm, row) {
		const apply_identity = () => {
			frm.set_value("siren_number", row.siren);
			if (row.tax_id) frm.set_value("tax_id", row.tax_id);
			frappe.show_alert({
				message: __("SIREN and VAT filled from SIRENE. Save, then add the address below."),
				indicator: "green",
			});
			this._offer_address(frm, row);
		};

		if (frm.doc.tax_id && row.tax_id && frm.doc.tax_id !== row.tax_id) {
			frappe.confirm(
				__("Replace the current Tax ID {0} with {1} (computed from SIREN {2})?", [
					frappe.utils.escape_html(frm.doc.tax_id),
					frappe.utils.escape_html(row.tax_id),
					frappe.utils.escape_html(row.siren),
				]),
				apply_identity,
				() => {
					frm.set_value("siren_number", row.siren);
					this._offer_address(frm, row);
				}
			);
		} else {
			apply_identity();
		}
	},

	_offer_address(frm, row) {
		if (!row.siret || frm.is_new()) return;
		const address = [row.address_line1, row.pincode, row.city].filter(Boolean).join(", ");
		frappe.confirm(
			__("Create the head-office address from SIRENE?<br><b>{0}</b><br>{1} (SIRET {2})", [
				frappe.utils.escape_html(row.name || ""),
				frappe.utils.escape_html(address),
				frappe.utils.escape_html(row.siret),
			]),
			() => {
				const doc = frappe.model.get_new_doc("Address");
				doc.address_title = row.name;
				doc.address_type = "Billing";
				doc.address_line1 = row.address_line1;
				doc.pincode = row.pincode;
				doc.city = row.city;
				doc.country = "France";
				doc.siret_number = row.siret;
				doc.is_primary_address = 1;
				doc.links = [
					{ link_doctype: frm.doctype, link_name: frm.doc.name },
				];
				frappe.set_route("Form", "Address", doc.name);
			}
		);
	},
};
