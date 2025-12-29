(() => {
  // ../etransactions/etransactions/public/js/file_preview.js
  frappe.provide("etransactions");
  etransactions.original_file_preview = (frm) => {
    if (frm.doc.ocr_original_file) {
      frappe.model.with_doc("File", frm.doc.ocr_original_file).then(() => {
        preview_file(frm);
      });
    }
    if (frm.doc.pending_purchase_invoice) {
      frappe.model.with_doc("Pending Purchase Invoice", frm.doc.pending_purchase_invoice).then(() => {
        const doc = frappe.get_doc("Pending Purchase Invoice", frm.doc.pending_purchase_invoice);
        let msg = "";
        if (Math.abs(frm.doc.grand_total) != Math.abs(doc.supplier_grand_total)) {
          msg += `<div>${__("There is a difference between the total amount based on the data extraction (")} ${format_currency(Math.abs(doc.supplier_grand_total), frm.doc.currency)} ${__(") and this")}  ${__(frm.doctype).toLowerCase()} (${format_currency(Math.abs(frm.doc.grand_total), frm.doc.currency)} ).</div>`;
        }
        if (Math.abs(frm.doc.total_taxes_and_charges) != Math.abs(doc.supplier_tax_amount)) {
          msg += `<div>${__("There is a difference between the total taxes based on the data extraction (")} ${format_currency(Math.abs(doc.supplier_tax_amount), frm.doc.currency)} ${__(") and this")} ${__(frm.doctype).toLowerCase()} (${format_currency(Math.abs(frm.doc.total_taxes_and_charges), frm.doc.currency)} ).</div>`;
        }
        frm.dashboard.clear_headline();
        frm.dashboard.set_headline(msg, "orange");
      });
    }
  };
  var preview_file = (frm) => {
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
  };

  // ../etransactions/etransactions/public/js/document_analyzer.js
  frappe.provide("etransactions");
  etransactions.DocumentAnalyzer = class DocumentAnalyzer {
    constructor(frm) {
      this.frm = frm;
      this.show_file_uploader();
    }
    show_file_uploader() {
      const fieldname = "ocr_html";
      const $wrapper = this.frm.fields_dict[fieldname].$wrapper.empty();
      new frappe.ui.FileUploader({
        folder: frappe.boot.attachments_folder,
        doctype: this.frm.doctype,
        docname: this.frm.doc.name,
        frm: this.frm,
        fieldname,
        wrapper: $wrapper,
        make_attachments_public: false,
        restrictions: {
          allowed_file_types: ["image/*", "application/pdf"]
        },
        on_success: (file_doc, response) => {
          if (!this.frm.is_new()) {
            this.add_to_attachments(file_doc);
            this.frm.sidebar.reload_docinfo();
          }
        }
      });
    }
    add_to_attachments(attachment) {
      var form_attachments = this.get_attachments();
      for (var i in form_attachments) {
        if (form_attachments[i]["name"] === attachment.name)
          return;
      }
      form_attachments.push(attachment);
    }
    get_attachments() {
      return this.frm.get_docinfo().attachments || [];
    }
  };
})();
//# sourceMappingURL=etransactions.bundle.QPFIN3AS.js.map
