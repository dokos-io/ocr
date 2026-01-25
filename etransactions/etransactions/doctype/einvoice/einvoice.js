// Copyright (c) 2024, ALYF GmbH, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("eInvoice", {
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
	create_supplier: function (frm) {
		frappe.model.open_mapped_doc({
			method: "etransactions.etransactions.doctype.einvoice.einvoice.create_supplier",
			frm: frm,
		});
	},
	create_supplier_address: function (frm) {
		frappe.model.open_mapped_doc({
			method: "etransactions.etransactions.doctype.einvoice.einvoice.create_supplier_address",
			frm: frm,
		});
	},
});

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
