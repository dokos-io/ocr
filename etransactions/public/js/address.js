// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt

// An Address is an establishment: show where e-invoices billed to it are routed —
// its own e-invoicing address (matched on its SIRET) or the customer's.
frappe.ui.form.on("Address", {
	refresh(frm) {
		if (!frappe.boot.einvoicing_enabled) return;
		const field = frm.fields_dict.etransactions_routing_html;
		if (!field) return;
		const $wrap = $(field.wrapper).empty();
		if (frm.is_new()) return;

		frappe
			.xcall("etransactions.plateforme_agreee.directory.get_address_routing", {
				address: frm.doc.name,
			})
			.then((rows) => {
				$wrap.empty();
				(rows || []).forEach((row) => _draw_address_routing($wrap, row, rows.length > 1));
			});
	},
});

function _draw_address_routing($wrap, row, show_customer) {
	const esc = frappe.utils.escape_html;
	const customer = show_customer
		? `<span class="text-muted small">${esc(row.customer)}</span>`
		: "";
	let html;
	if (row.line && row.own) {
		html = `<span class="et-routing-label">${__(
			"E-invoices for this address are sent to"
		)}</span>
			<code class="et-routing-id">${esc(row.line.identifier)}</code>
			<span class="indicator-pill green">${__("This establishment")}</span>`;
	} else if (row.line) {
		html = `<span class="et-routing-label">${__(
			"E-invoices for this address are sent to"
		)}</span>
			<code class="et-routing-id">${esc(row.line.identifier)}</code>
			<span class="indicator-pill blue">${__("Customer's e-invoicing address")}</span>`;
	} else {
		html = `<span class="indicator-pill gray">${__("No e-invoicing address")}</span>
			<span class="text-muted small">${__("Sync the directory from the customer.")}</span>`;
	}
	const $row = $(`<div class="et-routing">${customer}${html}</div>`).appendTo($wrap);
	$(`<a class="small">${__("Open customer")} →</a>`)
		.on("click", () => frappe.set_route("Form", "Customer", row.customer))
		.appendTo($row);
}
