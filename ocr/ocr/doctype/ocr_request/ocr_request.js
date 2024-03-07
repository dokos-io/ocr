// Copyright (c) 2023, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("OCR Request", {
	refresh(frm) {
		frm.add_custom_button(__('Trigger an analysis'), function() {
			frm.call("make_analysis");
		}, __("Actions"));

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
