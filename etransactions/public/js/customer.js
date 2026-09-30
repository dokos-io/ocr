// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("Customer", {
	refresh(frm) {
		// eTransactions is opt-in per site: nothing e-invoicing shows unless the
		// feature is activated in eTransactions Settings.
		if (!frappe.boot.einvoicing_enabled) return;

		if (
			frm.fields_dict.etransactions_wizard_html &&
			etransactions.EinvoiceReadinessIndicator
		) {
			frm._et_readiness =
				frm._et_readiness || new etransactions.EinvoiceReadinessIndicator(frm);
			// The widget surfaces the single "Sync directory" action; we own the
			// company-picker. Sync is meaningless until the customer is saved.
			frm._et_readiness.sync_action = frm.is_new() ? null : () => _sync_with_picker(frm);
			frm._et_readiness.refresh();
		}

		// Scope the default e-invoicing address to this customer's own active lines.
		frm.set_query("default_directory_line", () => ({
			filters: { customer: frm.doc.name, line_status: "active" },
		}));

		// Offer only CEF EAS schemes — anything else fails EN16931 (BR-CL-25).
		frm.set_query("etransactions_electronic_address_scheme", () => ({
			query: "etransactions.overrides.master_data.eas_scheme_query",
		}));

		// Pappers (ERPNext France) does the same French company lookup; only offer SIRENE
		// when Pappers is not enabled, to avoid two redundant autofill entry points.
		if (etransactions.sirene && !frappe.boot.pappers_enabled) {
			frm.add_custom_button(
				__("Fill from SIRENE"),
				() => etransactions.sirene.open(frm),
				__("eInvoicing")
			);
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
					__("Sync")
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

// "E-invoicing address" section: the address the customer's invoices are routed to,
// then — only when the customer has several establishments — each address with its
// SIRET and the e-invoicing address bound to it.
function _render_establishments(frm) {
	const field = frm.fields_dict.pa_establishments_html;
	if (!field) return;
	const $wrap = $(field.wrapper).empty();
	_toggle_default_line(frm, false);

	if (frm.is_new()) {
		$wrap.html(
			`<div class="text-muted small">${__(
				"Save the customer first to see its e-invoicing address."
			)}</div>`
		);
		return;
	}

	$wrap.html(
		`<div class="text-muted small">${frappe.utils.icon("loading-indicator")} ${__(
			"Loading e-invoicing address…"
		)}</div>`
	);

	Promise.all([
		frappe.xcall("etransactions.plateforme_agreee.directory.get_customer_routing", {
			customer: frm.doc.name,
		}),
		frappe.xcall("etransactions.plateforme_agreee.directory.get_party_establishments", {
			party_type: "Customer",
			party: frm.doc.name,
		}),
	]).then(([routing, rows]) => {
		$wrap.empty();
		_draw_routing_summary($wrap, frm, routing);
		_toggle_default_line(frm, routing.needs_default);
		// A single establishment is fully described by the summary above.
		if ((rows || []).length > 1 || routing.active_count > 1) {
			_draw_establishments($wrap, rows || []);
		}
	});
}

// The default e-invoicing address is only a choice when the directory lists several
// addresses and none is picked automatically (or with advanced routing).
function _toggle_default_line(frm, needs_default) {
	const advanced = (frappe.boot.einvoicing_features || {}).advanced_routing;
	frm.toggle_display(
		"default_directory_line",
		!!(needs_default || advanced || frm.doc.default_directory_line)
	);
}

function _draw_routing_summary($wrap, frm, routing) {
	const esc = frappe.utils.escape_html;
	let html;
	if (routing.line) {
		html = `<span class="et-routing-label">${__("Invoices are sent to")}</span>
			<code class="et-routing-id">${esc(routing.line.identifier)}</code>
			<span class="indicator-pill green">${__("Active")}</span>`;
	} else if (routing.needs_default) {
		html = `<span class="indicator-pill orange">${__("Several e-invoicing addresses")}</span>
			<span class="text-muted small">${__("Choose the default one below.")}</span>`;
	} else if (frm.doc.directory_update_date) {
		html = `<span class="indicator-pill gray">${__("Not found in the directory")}</span>
			<span class="text-muted small">${__("This customer cannot receive e-invoices yet.")}</span>`;
	} else {
		html = `<span class="indicator-pill gray">${__("Not synced yet")}</span>
			<span class="text-muted small">${__(
				"Sync the directory to find this customer's e-invoicing address."
			)}</span>`;
	}
	$(`<div class="et-routing">${html}</div>`).appendTo($wrap);
}

function _draw_establishments($wrap, rows) {
	if (!rows.length) {
		$wrap.append(
			`<div class="text-muted small">${__(
				"No addresses linked to this customer yet."
			)}</div>`
		);
		return;
	}

	const esc = frappe.utils.escape_html;
	const $table = $(`
		<table class="et-estab">
			<thead>
				<tr>
					<th scope="col">${__("Establishment")}</th>
					<th scope="col">${__("SIRET")}</th>
					<th scope="col">${__("E-invoicing Address")}</th>
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
			`<button type="button" class="et-icon-btn" aria-label="${__("Open address {0}", [
				esc(row.title || row.address),
			])}" title="${__("Open address")}">${frappe.utils.icon("edit", "sm")}</button>`
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
			line.line_status === "active"
				? "green"
				: line.line_status === "upcoming"
				? "blue"
				: "gray";
		const status_labels = {
			upcoming: __("Upcoming"),
			active: __("Active"),
			disabled: __("Disabled"),
			inactive: __("Inactive"),
		};
		const label =
			line.routing_code_name ||
			status_labels[line.line_status] ||
			__(line.line_status || "");
		let html = `<code class="et-routing-id">${esc(
			line.identifier || ""
		)}</code> <span class="indicator-pill ${color}">${esc(label)}</span>`;
		if (line.commitment_required) {
			html += ` <span class="et-estab-commit" title="${__(
				"Every invoice to this route needs a purchase-order / commitment number."
			)}">${__("commitment required")}</span>`;
		}
		return html;
	}
	return `<span class="text-muted small">${__(
		"Uses the customer's e-invoicing address"
	)}</span>`;
}
