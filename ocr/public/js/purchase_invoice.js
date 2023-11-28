frappe.provide("ocr");

frappe.ui.form.on('Purchase Invoice', {
	refresh(frm) {
		if (frm.doc.ocr_original_file) {
			frappe.model.with_doc("File", frm.doc.ocr_original_file).then(() => {
				frm.trigger("preview_file")
			});
		}


		if (frm.doc.ocr_request) {
			frappe.model.with_doc("OCR Request", frm.doc.ocr_request).then(() => {
				const doc = frappe.get_doc("OCR Request", frm.doc.ocr_request)
				console.log(doc)
			});
		}
	},

	preview_file(frm) {
		let $preview = "";
		const file_doc = frappe.model.get_doc("File", frm.doc.ocr_original_file);
		let file_extension = file_doc.file_type.toLowerCase();

		if (frappe.utils.is_image_file(file_doc.file_url)) {
			$preview = $(`<div class="img_preview">
				<img
					class="img-responsive"
					src="${frappe.utils.escape_html(file_doc.file_url)}"
					onerror="${frm.toggle_display("ocr_html", false)}"
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
			frm.toggle_display("ocr_html", true);
			frm.get_field("ocr_html").$wrapper.html($preview);
		}
	},
})