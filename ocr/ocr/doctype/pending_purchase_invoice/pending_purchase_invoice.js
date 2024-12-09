// Copyright (c) 2024, Dokos SAS and contributors
// For license information, please see license.txt

frappe.provide("ocr.pending_invoice");

frappe.ui.form.on("Pending Purchase Invoice", {
	refresh(frm) {

		$('[data-fieldname="__column_1"]').removeClass("col-sm-6").addClass("col-sm-4")
		$('[data-fieldname="preview_column"]').removeClass("col-sm-6").addClass("col-sm-8")
		frm.trigger("show_preview")
		frm.trigger("build_match_section")
	},

	async show_preview(frm) {
		let $preview = "";
		await frappe.model.with_doc("File", frm.doc.file);
		const file_doc = frappe.model.get_doc("File", frm.doc.file);
		let file_extension = file_doc.file_type.toLowerCase();
		const file_preview_field = frm.get_field("invoice_preview");

		if (frappe.utils.is_image_file(file_doc.file_url)) {
			$preview = $(`<div class="img_preview">
				<img
					class="img-responsive"
					src="${frappe.utils.escape_html(file_doc.file_url)}"
					onerror="${file_preview_field.toggle(false)}"
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
			file_preview_field.toggle(true);
			file_preview_field.$wrapper.html($preview);
		}
	},

	build_match_section(frm) {
		const matching_section = frm.get_field("matching_section");
		frappe.require("ocr_dashboard.bundle.js", () => {
			new ocr.pending_invoice.match_tab(matching_section.$wrapper[0], frm.doc, {purchase_order: 1})
		})
	}
});
