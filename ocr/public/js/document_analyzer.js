frappe.provide("ocr")

ocr.DocumentAnalyzer = class DocumentAnalyzer {
	constructor(frm) {
		this.frm = frm;
		this.show_file_uploader()
	}

	show_file_uploader() {
		const fieldname = "ocr_html"
		const $wrapper = this.frm.fields_dict[fieldname].$wrapper.empty()
		new frappe.ui.FileUploader({
			folder: frappe.boot.attachments_folder,
			doctype: this.frm.doctype,
			docname: this.frm.doc.name,
			frm: this.frm,
			fieldname: fieldname,
			wrapper: $wrapper,
			make_attachments_public: false,
			restrictions: {
				allowed_file_types: ["image/*", "application/pdf"],
			},
			on_success: (file_doc, response) => {
				if (!this.frm.is_new()) {
					this.add_to_attachments(file_doc)
					this.frm.sidebar.reload_docinfo();
				}
			},
		});
	}

	add_to_attachments(attachment) {
		var form_attachments = this.get_attachments();
		for (var i in form_attachments) {
			// prevent duplicate
			if (form_attachments[i]["name"] === attachment.name) return;
		}
		form_attachments.push(attachment);
	}

	get_attachments() {
		return this.frm.get_docinfo().attachments || [];
	}
}
