// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("Customer", {
	refresh(frm) {
		if (frm.fields_dict.etransactions_wizard_html && etransactions.EinvoiceReadinessIndicator) {
			frm._et_readiness = frm._et_readiness || new etransactions.EinvoiceReadinessIndicator(frm);
			// The widget surfaces the single "Sync directory" action; we own the
			// company-picker. Sync is meaningless until the customer is saved.
			frm._et_readiness.sync_action = frm.is_new() ? null : () => _sync_with_picker(frm);
			frm._et_readiness.refresh();
		}

		// Scope the default routing line to this customer's own directory lines.
		frm.set_query("default_directory_line", () => ({ filters: { customer: frm.doc.name } }));

		// Offer only CEF EAS schemes — anything else fails EN16931 (BR-CL-25).
		frm.set_query("etransactions_electronic_address_scheme", () => ({
			query: "etransactions.overrides.master_data.eas_scheme_query",
		}));

		if (etransactions.sirene) {
			frm.add_custom_button(__("Fill from SIRENE"), () => etransactions.sirene.open(frm));
		}

		_render_establishments(frm);
	},
});

// Resolve which company's platform to sync against (prompt only when ambiguous),
// then run the directory sync.
function _sync_with_picker(frm) {
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
}

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

// Read-only "Establishments & Routing" table: each address (establishment) of the
// customer with its SIRET and the directory line bound to it. Re-adds the view that
// was dropped with the e-invoicing wizard, reusing the get_party_establishments API.
function _render_establishments(frm) {
	const field = frm.fields_dict.pa_establishments_html;
	if (!field) return;
	const $wrap = $(field.wrapper).empty();

	if (frm.is_new()) {
		$wrap.html(`<div class="text-muted small">${__("Save the customer first to see its establishments and routing.")}</div>`);
		return;
	}

	$wrap.html(`<div class="text-muted small">${frappe.utils.icon("loading-indicator")} ${__("Loading establishments…")}</div>`);

	frappe.call({
		method: "etransactions.plateforme_agreee.directory.get_party_establishments",
		args: { party_type: "Customer", party: frm.doc.name },
		callback: (r) => _draw_establishments($wrap, r.message || []),
	});
}

function _draw_establishments($wrap, rows) {
	$wrap.empty();
	if (!rows.length) {
		$wrap.html(`<div class="text-muted small">${__("No addresses linked to this customer yet.")}</div>`);
		return;
	}

	const esc = frappe.utils.escape_html;
	const $table = $(`
		<table class="et-estab">
			<thead>
				<tr>
					<th scope="col">${__("Establishment")}</th>
					<th scope="col">${__("SIRET")}</th>
					<th scope="col">${__("Routing")}</th>
					<th scope="col"><span class="sr-only">${__("Actions")}</span></th>
				</tr>
			</thead>
			<tbody></tbody>
		</table>
	`);
	const $body = $table.find("tbody");

	rows.forEach((row) => {
		const primary = row.is_primary
			? ` <span class="et-estab-primary">${__("primary")}</span>`
			: "";
		const $row = $(`
			<tr>
				<td><span class="et-estab-title">${esc(row.title || row.address)}</span>${primary}</td>
				<td class="et-estab-siret">${esc(row.siret_number || "—")}</td>
				<td>${_routing_cell(row)}</td>
				<td class="et-estab-actions"></td>
			</tr>
		`);
		const $open = $(
			`<button type="button" class="et-icon-btn" aria-label="${__("Open address {0}", [esc(row.title || row.address)])}" title="${__("Open address")}">${frappe.utils.icon("edit", "sm")}</button>`,
		);
		$open.on("click", () => frappe.set_route("Form", "Address", row.address));
		$row.find(".et-estab-actions").append($open);
		$body.append($row);
	});

	$wrap.append($table);
}

function _routing_cell(row) {
	const esc = frappe.utils.escape_html;
	const line = row.line;
	if (!row.siret_number) {
		return `<span class="indicator-pill orange">${__("No SIRET")}</span>`;
	}
	if (line) {
		const color =
			line.line_status === "active" ? "green" : line.line_status === "upcoming" ? "blue" : "gray";
		let html = `<span class="indicator-pill ${color}">${esc(line.routing_code_name || line.line_status)}</span>`;
		if (line.commitment_required) {
			html += ` <span class="et-estab-commit" title="${__("Every invoice to this route needs a purchase-order / commitment number.")}">${__("commitment required")}</span>`;
		}
		return html;
	}
	return `<span class="indicator-pill gray">${__("No routing line — sync directory")}</span>`;
}
