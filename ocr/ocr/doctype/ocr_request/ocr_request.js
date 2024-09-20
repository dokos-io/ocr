// Copyright (c) 2023, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("OCR Request", {
	refresh(frm) {
		if (frm.doc.transaction_type != "Purchase Invoice") {
			frm.add_custom_button(__('Trigger an analysis'), function() {
				frm.call("make_analysis");
			}, __("Actions"));
		}

		if (frm.doc.status != "Closed") {
			frm.add_custom_button(__('Close'), function() {
				frm.call("close_request").then(() => { frm.reload_doc() });
			}, __("Actions"));
		} else {
			frm.add_custom_button(__('Reopen'), function() {
				frm.call("open_request").then(() => { frm.reload_doc() });
			}, __("Actions"));
		}

		if (["Analysis Completed", "Error", "Purchase Order Created"].includes(frm.doc.status)) {
			frm.page.set_primary_action(__('Process Request'), function() {
				frm.events.trigger_purchase_invoice_creation(frm)
			})

			if (!frm.doc.supplier) {
				frm.add_custom_button(__('Create supplier'), () => {
					const supplier_name_list = frm.doc.header_mapping.filter(f => f.key == "VENDOR_NAME")
					const vat_number_list = frm.doc.header_mapping.filter(f => f.key == "VENDOR_VAT_NUMBER")

					const supplier = frappe.model.get_new_doc("Supplier");
					supplier["supplier_name"] = supplier_name_list.length ? supplier_name_list[0]["value"] : "";
					supplier["company_search"] = supplier_name_list.length ? supplier_name_list[0]["value"] : "";
					supplier["tax_id"] = vat_number_list.length > 0 ? vat_number_list[0]["value"]: "";

					frappe.ui.form.make_quick_entry(
						"Supplier",
						null,
						null,
						supplier,
						null
					)
				});
			}

			frm.add_custom_button(__('Create a purchase order'), () => {
				new PurchaseOrderCreator(frm)
			}, __("Actions"));

			frm.add_custom_button(__('Link with a purchase order'), () => {
				new PurchaseOrderLink(frm)
			}, __("Actions"));
		}

		if (frm.doc.file) {
			frappe.model.with_doc("File", frm.doc.file).then(() => {
				frm.trigger("preview_file")
			});
		}
	},

	trigger_purchase_invoice_creation(frm, purchase_orders) {
		return frappe.call({
			method: "create_purchase_documents",
			doc: frm.doc,
			args: {
				orders: purchase_orders
			}
		}).then((r) => {
			frm.reload_doc()
			if (r.message && r.message.status == "Error") {
				frappe.show_alert({
					indicator: "red",
					message: r.message.message
				})
			} else {
				frappe.show_alert({
					indicator: "green",
					message: __("Action completed with success")
				})
			}
		})
	},

	preview_file(frm) {
		let $preview = "";
		const file_doc = frappe.model.get_doc("File", frm.doc.file);
		let file_extension = file_doc.file_type.toLowerCase();

		if (frappe.utils.is_image_file(file_doc.file_url)) {
			$preview = $(`<div class="img_preview">
				<img
					class="img-responsive"
					src="${frappe.utils.escape_html(file_doc.file_url)}"
					onerror="${frm.toggle_display("document_html", false)}"
				/>
			</div>`);
		} else if (frappe.utils.is_video_file(file_doc.file_url)) {
			$preview = $(`<div class="img_preview">
				<video width="480" height="320" controls>
					<source src="${frappe.utils.escape_html(file_doc.file_url)}">
					${__("Your browser does not support the video element.")}
				</video>
			</div>`);
		} else if (file_extension === "pdf") {
			$preview = $(`<div class="img_preview">
				<object style="background:#323639;" width="100%">
					<embed
						style="background:#323639;"
						width="100%"
						height="1190"
						src="${frappe.utils.escape_html(file_doc.file_url)}" type="application/pdf"
					>
				</object>
			</div>`);
		} else if (file_extension === "mp3") {
			$preview = $(`<div class="img_preview">
				<audio width="480" height="60" controls>
					<source src="${frappe.utils.escape_html(file_doc.file_url)}" type="audio/mpeg">
					${__("Your browser does not support the audio element.")}
				</audio >
			</div>`);
		}

		if ($preview) {
			frm.toggle_display("document_html", true);
			frm.get_field("document_html").$wrapper.html($preview);
		}
	},
});


class PurchaseOrderCreator {
	constructor(frm) {
		this.frm = frm

		this.make_dialog()
	}

	make_dialog() {
		const dialog = new frappe.ui.Dialog({
			title: __("Create a new purchase order"),
			size: "extra-large",
			fields: [
				{
					label: "Supplier",
					fieldname: "supplier",
					fieldtype: "Link",
					options: "Supplier",
					reqd: 1,
					default: this.frm.doc.supplier
				},
				{
					fieldname: "items",
					fieldtype: "Table",
					label: __("Items"),
					cannot_add_rows: true,
					cannot_delete_rows: true,
					in_place_edit: true,
					data: this.get_items(),
					get_data: () => {
						return this.frm.doc.line_items_mapping;
					},
					fields: [
						{
							fieldtype: "Link",
							options: "Item",
							fieldname: "item_code",
							label: __("Item Code"),
							in_list_view: 1,
						},
						{
							fieldtype: "Small Text",
							fieldname: "item_name",
							label: __("Item Name"),
							read_only: 1,
							in_list_view: 1,
						},
						{
							fieldtype: "Small Text",
							fieldname: "description",
							label: __("Description"),
							read_only: 1,
							in_list_view: 1,
						}
					],
				},
			],
			primary_action: () => {
				const dialog_values = dialog.get_values();
				this.update_mapping(dialog_values)

				dialog.hide();
			},
			primary_action_label: __("Create a purchase order"),
		});
		dialog.show();
	}

	get_items() {
		return this.frm.doc.line_items_mapping.map(item => {
			return {
				item_code: item.item_code,
				item_name: item?.item?.substring(0, 140) || item?.product_code,
				description: item?.item || item?.product_code
			}
		})
	}

	update_mapping(values) {
		return frappe.call({
			method: "register_mapping",
			doc: this.frm.doc,
			args: {
				data: values,
			}
		}).then(res => {
			if (!res.exc) {
				this.frm.reload_doc()
				this.create_purchase_order()
			} else {
				frappe.show_alert(
					{
						indicator: "red",
						message: __("An error prevented the creation of the purchase order")
					}
				)
			}
		})
	}

	create_purchase_order() {
		frappe.model.open_mapped_doc({
			method: "ocr.ocr.doctype.ocr_request.ocr_request.make_purchase_order",
			frm: this.frm
		});
	}
}

class PurchaseOrderLink {
	constructor(frm) {
		this.frm = frm;
		this.make_dialog()
	}

	make_dialog() {
		const d = new frappe.ui.form.MultiSelectDialog({
			doctype: "Purchase Order",
			target: "Purchase Order",
			date_field: "transaction_date",
			size: "extra-large",
			setters: [
				{
					fieldtype: "Link",
					options: "Supplier",
					label: __("Supplier"),
					fieldname: "supplier",
				},
				{
					fieldtype: "Date",
					label: __("Transaction Date"),
					fieldname: "transaction_date",
				},
				{
					fieldtype: "Currency",
					label: __("Grand Total"),
					fieldname: "grand_total",
				},
				{
					fieldname: "ocr_request",
					fieldtype: "Check",
					label: __("Already linked to an OCR request"),
				}
			],
			primary_action_label: __("Select one or more sales orders"),
			get_query: () => {
				return {
					query: "ocr.ocr.doctype.ocr_request.ocr_request.get_purchase_orders",
					filters: {
						company: this.frm.doc.company,
						supplier: this.frm.doc.supplier,
						docstatus: 1,
						per_billed: ["<", 100.0],
						status: ["!=", "Closed"]
					},
				};
			},
			action: (purchase_orders) => {
				if (purchase_orders.length === 0) {
					frappe.msgprint(__("Please select at least one sales order"));
					return;
				}

				const rows = d.get_checked_items();
				if (!rows.every(row => row.supplier === rows[0].supplier)) {
					frappe.msgprint(__("Please select orders linked to the same supplier"));
					return;
				}

				frappe.call({
					method: "link_to_purchase_order",
					doc: this.frm.doc,
					args: {
						orders: purchase_orders
					}
				}).then(() => {
					this.frm.events.trigger_purchase_invoice_creation(this.frm, purchase_orders)
				})

				d.dialog.hide();
			},
			make_new_document: (e) => {
				if (e) {
					new PurchaseOrderCreator(this.frm)
				}
			}
		});
	}
}
