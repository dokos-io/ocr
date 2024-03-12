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

// class TextractAnalysisGetter {
// 	constructor(frm, request) {
// 		this.frm = frm;
// 		this.request = request

// 		this.fetch_analysis()
// 	}

// 	fetch_analysis() {
// 		const get_analysis = async () => {
// 			return frappe.call({
// 				method: "ocr.ocr.doctype.ocr_request.ocr_request.get_analysis",
// 				args: {
// 					request_id: this.request
// 				}
// 			})
// 		};

// 		let count = 0;
// 		const total_count = 100

// 		const interval = async () => {
// 			frappe.show_progress(
// 				__("Analysis in progress"),
// 				count,
// 				total_count,
// 				null,
// 				true
// 			);

// 			let analysis = await get_analysis();
// 			if (analysis.message.JobStatus === "SUCCEEDED") {
// 				frappe.hide_progress();
// 				new PurchaseInvoiceCreator(this.frm, analysis.message)
// 				return;
// 			}
	
// 			count++;
// 			console.log("ANALYSIS ", analysis);
			
// 			if (count >= total_count) {
// 				frappe.hide_progress();
// 				return;
// 			}

// 			setTimeout(interval, 5000);
// 		};

// 		interval()
// 	}
// }
