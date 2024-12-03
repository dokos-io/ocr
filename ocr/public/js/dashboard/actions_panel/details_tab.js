frappe.provide("ocr.ocr_dashboard");

ocr.ocr_dashboard.DetailsTab = class DetailsTab {
	constructor(opts) {
		$.extend(this, opts);
		this.make();
	}

	make() {
		this.panel_manager.actions_tab = "details-tab";

		this.details_field_group = new frappe.ui.FieldGroup({
			fields: this.get_detail_tab_fields(),
			body: this.actions_panel.$tab_content,
			card_layout: true,
		});
		this.details_field_group.make();

		if (this.transaction.file) {
			frappe.model.with_doc("File", this.transaction.file).then(() => {
				this.preview_file()
			});
		}
	}

	async update_ocr_request() {
		await frappe.call({
			method:
				"ocr.ocr.doctype.ocr_reconciliation_dashboard.ocr_reconciliation_dashboard.update_ocr_request",
			args: {
				ocr_request: this.transaction.name,
				data: this.details_field_group.get_values()
			},
		}).then((result) => {
			this.details_field_group.get_field("save_ocr_request").toggle(false);
			this.details_field_group.dirty = false;

			this.transaction = result.message;
			this.details_field_group.refresh();
		});
	}

	show_save_button() {
		this.details_field_group.get_field("save_ocr_request").toggle(true);
		this.details_field_group.refresh();
	}

	get_detail_tab_fields() {
		return [
			{
				label: __("Company"),
				fieldname: "company",
				fieldtype: "Link",
				options: "Company",
				onchange: () => {
					if (this.details_field_group.get_value("company") != this.transaction.company) {
						this.show_save_button()
					}
				},
				default: this.transaction.company,
			},
			{
				label: __("Supplier"),
				fieldname: "supplier",
				fieldtype: "Link",
				options: "Supplier",
				onchange: () => {
					if (this.details_field_group.get_value("supplier") != this.transaction.supplier) {
						this.show_save_button()
					}
				},
				default: this.transaction.supplier,
			},
			{
				fieldtype: "Column Break"
			},
			{
				label: __("Invoice Number"),
				fieldname: "bill_no",
				fieldtype: "Data",
				onchange: () => {
					if (this.details_field_group.get_value("bill_no") != this.transaction.bill_no) {
						this.show_save_button()
					}
				},
				default: this.transaction.bill_no,
			},
			{
				label: __("Invoice Date"),
				fieldname: "bill_date",
				fieldtype: "Date",
				onchange: () => {
					if (this.details_field_group.get_value("bill_date") != frappe.datetime.obj_to_str(this.transaction.bill_date || this.transaction.creation)) {
						this.show_save_button()
					}
				},
				default: this.transaction.bill_date || this.transaction.creation,
			},
			{
				label: __("Due Date"),
				fieldname: "due_date",
				fieldtype: "Date",
				onchange: () => {
					if (this.details_field_group.get_value("due_date") != frappe.datetime.obj_to_str(this.transaction.due_date)) {
						this.show_save_button()
					}
				},
				default: this.transaction.due_date,
			},
			{
				fieldtype: "Section Break",
				hide_border: 1
			},
			{
				label: __("Net Total"),
				fieldname: "net_total",
				fieldtype: "Currency",
				default: this.transaction.net_total,
				options: this.transaction.currency,
				read_only: 1,
			},
			{
				label: __("Tax Total"),
				fieldname: "tax_total",
				fieldtype: "Currency",
				default: this.transaction.tax_total,
				options: this.transaction.currency,
				read_only: 1,
			},
			{
				fieldtype: "Column Break"
			},
			{
				label: __("Grand Total"),
				fieldname: "grand_total",
				fieldtype: "Currency",
				default: this.transaction.grand_total,
				options: this.transaction.currency,
				read_only: 1,
			},
			{
				fieldtype: "Section Break",
			},
			{
				fieldtype: "Data",
				hidden: 1,
				fieldname: "hidden_alignment_field"
			},
			{
				fieldtype: "Column Break"
			},
			{
				label: __("Save"),
				fieldname: "save_ocr_request",
				fieldtype: "Button",
				hidden: true,
				primary: true,
				click: () => this.update_ocr_request(),
			},
			{
				fieldtype: "Section Break",
			},
			{
				label: __("Invoice Preview"),
				fieldname: "invoice_preview_html",
				fieldtype: "HTML",
			},
		];
	}

	preview_file() {
		let $preview = "";
		const file_doc = frappe.model.get_doc("File", this.transaction.file);
		let file_extension = file_doc.file_type.toLowerCase();
		const file_preview_field = this.details_field_group.get_field("invoice_preview_html");

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
	}
}