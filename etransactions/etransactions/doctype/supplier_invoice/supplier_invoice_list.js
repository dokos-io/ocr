frappe.listview_settings["Supplier Invoice"] = {
	hide_name_column: true,
	onload: function (listview) {
		listview.page.add_inner_button(__("Upload Invoices"), function () {
			new frappe.ui.FileUploader({
				make_attachments_public: false,
				on_success: (file_doc) => {
					frappe.call({
						method: "etransactions.etransactions.doctype.supplier_invoices_basket.supplier_invoices_basket.create_basket_from_files",
						args: {
							file_names: [file_doc.name],
						}
					}).then(r => {
						if (r.message) {
							frappe.show_alert(
								__("Basket {0} created", [listview.basket_name]),
								5
							);
						}
					})
				},
			});
		});
	},
};