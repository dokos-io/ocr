// Copyright (c) 2026, ALYF GmbH, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("eInvoice", {
	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		_add_pa_buttons(frm);

		if (frm.doc.pa_flow_id) {
			etransactions.lifecycle.attach(frm, {
				einvoice: frm.doc.name,
				side: frm.doc.einvoice_type === "Outgoing" ? "sale" : "purchase",
				pa_status: frm.doc.pa_status,
			});
		}
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

function _send_to_plateform(frm) {
	frm.call({
		method: "send_to_plateform",
		doc: frm.doc,
		freeze: true,
		freeze_message: __("Submitting to accredited platform…"),
	}).then(() => frm.reload_doc());
}

function _add_pa_buttons(frm) {
	const pa_status = frm.doc.pa_status || "";
	const pa_flow_id = frm.doc.pa_flow_id;

	if (frm.doc.einvoice_type === "Outgoing" && (!pa_flow_id || pa_status === "error")) {
		frm.add_custom_button(__("Send to the accredited platform"), () => {
			if (pa_status === "error") {
				frappe.confirm(
					__("The previous submission was rejected by the accredited platform. Send this e-invoice again?"),
					() => _send_to_plateform(frm)
				);
			} else {
				_send_to_plateform(frm);
			}
		}, __("Accredited platform"));
	}

	if (pa_flow_id) {
		frm.add_custom_button(__("Refresh PA Status"), () => {
			frm.call({
				method: "refresh_pa_status",
				doc: frm.doc,
				freeze: true,
				freeze_message: __("Refreshing status…"),
			}).then(() => frm.reload_doc());
		}, __("Accredited platform"));
	}
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
