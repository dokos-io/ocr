// Copyright (c) 2023, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("OCR Request", {
	refresh(frm) {
		if (frm.doc.transaction_type != "Purchase Invoice") {
			frm.add_custom_button(__('Trigger an analysis'), function() {
				frm.call("make_analysis");
			}, __("Actions"));
		}

		frm.add_custom_button(__('Close'), function() {
			frm.call("close_request").then(() => { frm.reload_doc() });
		}, __("Actions"));

		if (["Analysis Completed", "Error"].includes(frm.doc.status) && frm.doc.transaction_type == "Purchase Invoice") {
			frm.page.set_primary_action(__('Create/match purchase invoice'), function() {
				frappe.call({
					method: "create_purchase_invoice",
					doc: frm.doc
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
							message: __("Purchase invoice created")
						})
					}
				})
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
		}

		if (frm.doc.file) {
			frappe.model.with_doc("File", frm.doc.file).then(() => {
				frm.trigger("preview_file")
			});
		}
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
				item_name: item.item.substring(0, 140),
				description: item.item
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