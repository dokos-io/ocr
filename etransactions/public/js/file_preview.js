frappe.provide("etransactions");

etransactions.original_file_preview = (frm) => {
	if (frm.doc.ocr_original_file) {
		frappe.model.with_doc("File", frm.doc.ocr_original_file).then(() => {
			preview_file(frm)
		});
	}


	if (frm.doc.supplier_invoice) {
		frappe.model.with_doc("Supplier Invoice", frm.doc.supplier_invoice).then(() => {
			const doc = frappe.get_doc("Supplier Invoice", frm.doc.supplier_invoice)
			let msg = ""

			if (Math.abs(frm.doc.grand_total) != Math.abs(doc.supplier_grand_total)) {
				msg += `<div>${__("There is a difference between the total amount based on the data extraction ({0}) and this {1} ({2}).", [
					format_currency(Math.abs(doc.supplier_grand_total), frm.doc.currency),
					__(frm.doctype),
					format_currency(Math.abs(frm.doc.grand_total), frm.doc.currency),
				])}</div>`
			}

			if (Math.abs(frm.doc.total_taxes_and_charges) != Math.abs(doc.supplier_tax_amount)) {
				msg += `<div>${__("There is a difference between the total taxes based on the data extraction ({0}) and this {1} ({2}).", [
					format_currency(Math.abs(doc.supplier_tax_amount), frm.doc.currency),
					__(frm.doctype),
					format_currency(Math.abs(frm.doc.total_taxes_and_charges), frm.doc.currency),
				])}</div>`
			}

			frm.dashboard.clear_headline();
			frm.dashboard.set_headline(msg, "orange")
		});
	}
}


/**
 * Markup previewing an attached original invoice, or "" when the type has no preview.
 *
 * Shared by the Purchase Invoice "Original Invoice" tab and the Supplier Invoice
 * preview field: both show the same received file, and an e-invoice carrying only
 * structured data (no embedded PDF) must not render as an empty panel on either.
 *
 * @param {object} file_doc - a File document (needs file_url and file_type)
 * @param {object} [options]
 * @param {string} [options.einvoice] - eInvoice to link to from the XML fallback
 */
etransactions.file_preview_html = (file_doc, { einvoice } = {}) => {
	// '#' terminates a URL fragment, so an unescaped one truncates the src.
	const file_url = (file_doc.file_url || "").replace(/#/g, "%23");
	const safe_url = frappe.utils.escape_html(file_url);
	const file_extension = (file_doc.file_type || "").toLowerCase();

	if (frappe.utils.is_image_file(file_doc.file_url)) {
		return `<div class="img_preview">
			<img class="img-responsive" src="${safe_url}" />
		</div>`;
	}
	if (frappe.utils.is_video_file(file_doc.file_url)) {
		return `<div class="img_preview">
			<video width="480" height="320" controls>
				<source src="${safe_url}">
				${__("Your browser does not support the video element.")}
			</video>
		</div>`;
	}
	if (file_extension === "pdf") {
		return `<div class="img_preview">
			<object style="background:#323639;" width="100%">
				<embed style="background:#323639;" width="100%" height="1190"
					src="${safe_url}" type="application/pdf">
			</object>
		</div>`;
	}
	if (file_extension === "mp3") {
		return `<div class="img_preview">
			<audio width="480" height="60" controls>
				<source src="${safe_url}" type="audio/mpeg">
				${__("Your browser does not support the audio element.")}
			</audio>
		</div>`;
	}
	if (file_extension === "xml") {
		const einvoice_link = einvoice
			? `<a href="${frappe.utils.get_form_link("eInvoice", einvoice)}">${__("Open the eInvoice")}</a>`
			: "";
		return `<div class="img_preview" data-et-xml-preview="1">
			<div class="text-muted" style="padding:var(--padding-lg); border:1px dashed var(--border-color); border-radius:var(--border-radius-md);">
				<p>${__("This e-invoice carries no embedded PDF, only structured data.")}</p>
				<p>
					<a href="${safe_url}" target="_blank">${__("Download the XML")}</a>
					${einvoice_link ? " · " + einvoice_link : ""}
				</p>
			</div>
		</div>`;
	}
	return "";
};

const preview_file = (frm) => {
	const file_doc = frappe.model.get_doc("File", frm.doc.ocr_original_file);
	const html = etransactions.file_preview_html(file_doc, { einvoice: frm.doc.einvoice });

	frm.toggle_display("ocr_html", !!html);
	if (html) {
		frm.get_field("ocr_html").$wrapper.html(html);
	}
}
