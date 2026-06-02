// Copyright (c) 2026, ALYF GmbH, Dokos SAS and contributors
// For license information, please see license.txt

// Manual lifecycle statuses a user can report, grouped by side.
//   purchase: we received the invoice (we are the buyer)
//   sale:     we issued the invoice (we are the seller)
const LIFECYCLE_STATUSES = {
	purchase: [
		{ status: "in_hand", label: __("In Hand") },
		{ status: "approved", label: __("Approved") },
		{ status: "partially_approved", label: __("Partially Approved"), reason: true },
		{ status: "dispute", label: __("Disputed"), reason: true },
		{ status: "suspended", label: __("Suspended"), reason: true },
		{ status: "refused", label: __("Refused"), reason: true, confirm: true },
		{ status: "payment_sent", label: __("Payment Sent") },
	],
	sale: [
		{ status: "completed", label: __("Completed") },
		{ status: "payment_received", label: __("Payment Received") },
	],
};

frappe.ui.form.on("eInvoice", {
	refresh(frm) {
		if (frm.is_new() || !frm.doc.pa_flow_id) {
			return;
		}

		const side = frm.doc.einvoice_type === "Outgoing" ? "sale" : "purchase";
		for (const def of LIFECYCLE_STATUSES[side]) {
			frm.add_custom_button(
				def.label,
				() => send_lifecycle_status(frm, def),
				__("Report Status")
			);
		}

		render_lifecycle_events(frm);
	},

	setup(frm) {
		frm.set_query("company", function () {
			return {
				filters: {
					is_group: 0,
				},
			};
		});

		frm.set_query("purchase_order", function (doc) {
			return {
				filters: {
					docstatus: 1,
					company: doc.company,
				},
			};
		});

		frm.set_query("supplier_address", function (doc) {
			return {
				filters: [
					["Dynamic Link", "link_doctype", "=", "Supplier"],
					["Dynamic Link", "link_name", "=", doc.supplier],
				],
			};
		});

		frm.set_query("item", "items", function (doc, cdt, cdn) {
			return {
				filters: {
					is_purchase_item: 1,
				},
			};
		});

		frm.set_query("po_detail", "items", function (doc, cdt, cdn) {
			const row = locals[cdt][cdn];
			return {
				query: "etransactions.etransactions.doctype.einvoice.einvoice.po_item_query",
				filters: {
					parent: doc.purchase_order,
					item_code: row.item,
				},
			};
		});

		frm.set_query("tax_account", "taxes", function (doc, cdt, cdn) {
			return {
				filters: {
					account_type: "Tax",
					company: doc.company,
				},
			};
		});
	},
});

function send_lifecycle_status(frm, def) {
	const run = (args) => {
		frm.call({
			method: "submit_lifecycle_status",
			doc: frm.doc,
			args: { status: def.status, ...args },
			freeze: true,
			freeze_message: __("Sending status to the accredited platform…"),
		}).then((r) => {
			if (!r.exc) {
				frappe.show_alert({
					message: __("Status '{0}' sent", [r.message || def.label]),
					indicator: "green",
				});
				frm.reload_doc();
			}
		});
	};

	if (!def.reason) {
		run({});
		return;
	}

	// A reason code (MDT-113) is mandatory for these statuses; fetch the
	// official CTC codelist for the chosen status and present it as a picker.
	frappe.xcall(
		"etransactions.etransactions.doctype.einvoice.einvoice.get_lifecycle_reason_codes",
		{ status: def.status }
	).then((codes) => {
		frappe.prompt(
			[
				{
					fieldname: "reason_code",
					fieldtype: "Select",
					label: __("Reason code"),
					options: (codes || []).join("\n"),
					reqd: 1,
				},
				{
					fieldname: "comment",
					fieldtype: "Small Text",
					label: __("Comment (optional)"),
				},
			],
			(values) => {
				const submit = () => run({ reason_code: values.reason_code, comment: values.comment });
				if (def.confirm) {
					frappe.confirm(
						__("Reporting '{0}' cannot be undone. Continue?", [def.label]),
						submit
					);
				} else {
					submit();
				}
			},
			__("Report '{0}'", [def.label]),
			__("Send")
		);
	});
}

function render_lifecycle_events(frm) {
	frappe.db
		.get_list("eInvoice Event", {
			filters: { einvoice: frm.doc.name },
			fields: ["direction", "status_label", "state", "status_datetime", "comment"],
			order_by: "status_datetime desc",
			limit: 20,
		})
		.then((events) => {
			if (!events || !events.length) {
				return;
			}

			const rows = events
				.map((e) => {
					const arrow =
						e.direction === "out"
							? '<span style="color:var(--blue-500)">&#8593; ' + __("Sent") + "</span>"
							: '<span style="color:var(--orange-500)">&#8595; ' + __("Received") + "</span>";
					const when = e.status_datetime
						? frappe.datetime.str_to_user(e.status_datetime)
						: "";
					const state =
						e.state === "error"
							? '<span style="color:var(--red-500)">' + e.state + "</span>"
							: e.state;
					return `<tr>
						<td>${arrow}</td>
						<td><strong>${frappe.utils.escape_html(e.status_label || "")}</strong></td>
						<td>${state}</td>
						<td>${when}</td>
						<td>${frappe.utils.escape_html(e.comment || "")}</td>
					</tr>`;
				})
				.join("");

			const html = `<table class="table table-bordered" style="margin-top:10px">
				<thead><tr>
					<th>${__("Direction")}</th>
					<th>${__("Status")}</th>
					<th>${__("State")}</th>
					<th>${__("Date/Time")}</th>
					<th>${__("Comment")}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>`;

			frm.dashboard.add_section(html, __("Lifecycle Statuses"));
		});
}

frappe.ui.form.on("E Invoice Item", {
	create_item: function (frm, cdt, cdn) {
		frappe.model.open_mapped_doc({
			method: "etransactions.etransactions.doctype.einvoice.einvoice.create_item",
			source_name: cdn,
		});
	},

	po_detail: function (frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.po_detail || (row.item && row.uom) || !frappe.model.can_read("Purchase Order")) {
			return;
		}

		frappe
			.xcall(
				"etransactions.etransactions.doctype.einvoice.einvoice.get_po_item_details",
				{ po_detail: row.po_detail }
			)
			.then((r) => {
				if (r.item_code && !row.item) {
					frappe.model.set_value(cdt, cdn, "item", r.item_code);
				}
				if (r.uom && !row.uom) {
					frappe.model.set_value(cdt, cdn, "uom", r.uom);
				}
			});
	},
});
