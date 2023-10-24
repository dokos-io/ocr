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
				frappe.call({
					method: "ocr.ocr.doctype.aws_textract_request.aws_textract_request.new_request",
					args: {
						file_doc: file_doc,
						response: response
					}
				}).then((r) => {
					new TextractAnalysisGetter(this.frm, r.message)
				})
			},
		});
	}
}

class TextractAnalysisGetter {
	constructor(frm, request) {
		this.frm = frm;
		this.request = request

		this.fetch_analysis()
	}

	fetch_analysis() {
		const get_analysis = async () => {
			return frappe.call({
				method: "ocr.ocr.doctype.aws_textract_request.aws_textract_request.get_analysis",
				args: {
					request_id: this.request
				}
			})
		};

		let count = 0;
		const total_count = 30

		const interval = async () => {
			frappe.show_progress(
				__("Analysis in progress"),
				count,
				total_count,
				null,
				true
			);

			let analysis = await get_analysis();
			if (analysis.message.JobStatus === "SUCCEEDED") {
				frappe.hide_progress();
				new PurchaseInvoiceCreator(this.frm, analysis.message)
				return;
			}
	
			count++;
			console.log("ANALYSIS ", analysis);
			
			if (count >= total_count) {
				return;
			}

			setTimeout(interval, 5000);
		};

		interval()
	}
}

class PurchaseInvoiceCreator {
	constructor(frm, analysis) {
		this.frm = frm
		this.analysis = analysis

		this.create_purchase_invoice()
	}

	create_purchase_invoice() {
		Object.keys(this.analysis.ParsedDokosData).map(key => {

			if (!Array.isArray(this.analysis.ParsedDokosData[key])) {
				this.frm.set_value(key, this.analysis.ParsedDokosData[key])
			} else {
				this.frm.doc.items = []
				this.analysis.ParsedDokosData[key].map(child => {
					this.frm.add_child(key, child)
				})
			}

		})
	}
}