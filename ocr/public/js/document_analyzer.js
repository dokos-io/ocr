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
				// new TextractAnalysisGetter(this.frm, r.message)

				this.add_to_attachments(file_doc)
				this.frm.sidebar.reload_docinfo();
				
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

class TextractAnalysisGetter {
	constructor(frm, request) {
		this.frm = frm;
		this.request = request

		this.fetch_analysis()
	}

	fetch_analysis() {
		const get_analysis = async () => {
			return frappe.call({
				method: "ocr.ocr.doctype.ocr_request.ocr_request.get_analysis",
				args: {
					request_id: this.request
				}
			})
		};

		let count = 0;
		const total_count = 100

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
				frappe.hide_progress();
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

		this.make_dialog()
	}

	make_dialog() {
		console.log(this.analysis)
		const dialog = new frappe.ui.Dialog({
			title: __("Create a new purchase invoice"),
			size: "extra-large",
			fields: [
				{
					label: "Supplier",
					fieldname: "supplier",
					fieldtype: "Link",
					options: "Supplier",
					reqd: 1,
					default: this.analysis.ParsedDokosData?.supplier
				},
				{
					fieldname: "items",
					fieldtype: "Table",
					label: __("Items"),
					cannot_add_rows: true,
					cannot_delete_rows: true,
					in_place_edit: true,
					data: this.analysis.ParsedDokosData?.items,
					get_data: () => {
						return this.analysis.ParsedDokosData?.items;
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
						},
					],
				},
			],
			primary_action: () => {
				const dialog_values = dialog.get_values();
				this.validated_analysis_data = this.analysis.ParsedDokosData;
				this.validated_analysis_data.supplier = dialog_values.supplier;
				dialog_values.items.forEach((item, idx) => {
					this.validated_analysis_data.items[idx].item_code = item.item_code
				})

				this.register_mapping()
				this.create_purchase_invoice()
				dialog.hide();
				this.frm.scroll_to_field("supplier")
			},
			primary_action_label: __("Create invoice"),
		});
		dialog.show();
	}

	register_mapping() {
		return frappe.call({
			method: "ocr.ocr.doctype.ocr_request.ocr_request.register_supplier_mapping",
			args: {
				validated_data: this.validated_analysis_data
			}
		}).then(res => {
			frappe.show_alert(
				{
					indicator: "green",
					message: __("Item codes and supplier registered for the next invoice")
				}
			)
		})
	}

	create_purchase_invoice() {
		const header_fields = frappe.get_meta("Purchase Invoice").fields.map(f => f.fieldname)
		Object.keys(this.validated_analysis_data).map(key => {
			if (!Array.isArray(this.validated_analysis_data[key])) {
				if (header_fields.includes(key)) {
					this.frm.set_value(key, this.validated_analysis_data[key])
				}
			} else {
				this.frm.doc.items = []
				this.validated_analysis_data[key].map(child => {
					this.frm.add_child(key, child)
				})
			}
		})
	}
}