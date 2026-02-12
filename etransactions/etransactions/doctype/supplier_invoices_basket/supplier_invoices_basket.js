// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("Supplier Invoices Basket", {
	refresh(frm) {
		new etransactions.DocumentAnalyzer(frm)
		new etransactions.BasketDashboard(frm)

		if (!frm.is_new() && !frm.__islocal && frm.doc.status == "Not Started") {
			frm.page.set_primary_action(__('Create purchase invoices'), function () {
				trigger_request_creation(frm);
			});
		}

		if (!frm.__islocal && frm.doc.status != "Not Started") {
			frm.page.clear_primary_action()
		}

		if (!frm.__islocal && frm.doc.status == "Closed") {
			frm.add_custom_button(__("Re-open"), () => {
				frm.set_value("status", "Not Started")
				frm.save()
			})
		}
	}
});

const trigger_request_creation = (frm) => {
	frappe.show_alert({
		indicator: "orange",
		message: __("Request creation in progress")
	})
	frm.page.clear_primary_action()

	frappe.call({
		method: "route_invoices",
		doc: frm.doc
	}).then(() => {
		frm.reload_doc()
		frappe.show_alert({
			indicator: "orange",
			message: __("Extraction in progress")
		})
	})
}


etransactions.BasketDashboard = class BasketDashboard {
	constructor(frm) {
		this.frm = frm;
		this.render();
	}

	render() {
		this.container = this.frm.fields_dict.dashboard_html.wrapper;
		if (!this.container) return;
		this.container.replaceChildren();

		if (this.frm.doc.status === "Not Started") {
			this._render_not_started();
		} else if (["In Progress", "Completed"].includes(this.frm.doc.status)) {
			this._render_in_progress();
		}
	}

	_render_not_started() {
		const attachments = this.frm.get_docinfo().attachments || [];
		const has_files = attachments.length > 0;

		const wrapper = this._el("div", ["text-center", "text-muted", "py-5"]);

		wrapper.appendChild(this._el("div", ["mt-2", "font-weight-bold", "text-dark"],
			has_files ? __("Ready to process") : __("Upload files to get started")));

		wrapper.appendChild(this._el("div", ["mt-1", "text-small"],
			has_files
				? __("Click 'Create purchase invoices' to begin processing your files.")
				: __("Attach your invoice files, then click 'Create purchase invoices'.")));

		this.container.appendChild(wrapper);
	}

	_render_in_progress() {
		this.loading = this._el("div", ["text-center", "text-muted", "py-5"]);
		this.loading.appendChild(this._el("div", ["bd-spinner"]));
		this.loading.appendChild(this._el("span", ["text-small"], __("Loading status...")));
		this.container.appendChild(this.loading);

		this.sections_wrapper = this._el("div");
		this.container.appendChild(this.sections_wrapper);

		this._render_statuses();
	}

	async _render_statuses() {
		try {
			const [ocr_requests, einvoices, supplier_invoices] = await Promise.all([
				frappe.db.get_list("OCR Request", {
					filters: { ocr_basket: this.frm.doc.name },
					fields: ["name", "status", "filename"],
				}),
				frappe.db.get_list("eInvoice", {
					filters: { supplier_invoices_basket: this.frm.doc.name },
					fields: ["name", "id", "seller_name"],
				}),
				frappe.db.get_list("Supplier Invoice", {
					filters: { ocr_basket: this.frm.doc.name },
					fields: ["name", "title"],
				}),
			]);

			if (this.loading) this.loading.remove();

			const total = ocr_requests.length + einvoices.length + supplier_invoices.length;
			if (total === 0) {
				this.sections_wrapper.appendChild(
					this._el("div", ["text-muted", "text-center", "py-4", "text-small"],
						__("No documents found yet. Processing may still be starting...")));
				return;
			}

			if (ocr_requests.length > 0) {
				this._render_section(__("OCR Requests"), ocr_requests.map((req) => ({
					doctype: "OCR Request",
					name: req.name,
					label: req.filename || req.name,
					status: req.status,
					color: this._get_indicator_color(req.status),
				})));
			}

			if (einvoices.length > 0) {
				this._render_section(__("eInvoices"), einvoices.map((inv) => ({
					doctype: "eInvoice",
					name: inv.name,
					label: inv.seller_name || inv.id || inv.name,
					status: __("Imported"),
					color: "green",
				})));
			}

			if (supplier_invoices.length > 0) {
				this._render_section(__("Supplier Invoices"), supplier_invoices.map((si) => ({
					doctype: "Supplier Invoice",
					name: si.name,
					label: si.title || si.name,
					status: __("Created"),
					color: "blue",
				})));
			}
		} catch (e) {
			console.error("BasketDashboard: failed to fetch statuses", e);
			if (this.loading) this.loading.remove();
			this.sections_wrapper.appendChild(
				this._el("div", ["alert", "alert-danger", "text-small"],
					__("Failed to load processing status. Please refresh.")));
		}
	}

	_render_section(title, items) {
		const section = this._el("div", ["mb-4", "etransactions-supplier-invoices-basket"]);

		const header = this._el("div", ["d-flex", "align-items-center", "mb-2"]);
		header.appendChild(this._el("span", ["text-uppercase", "text-muted", "text-small", "font-weight-bold"], title));
		header.appendChild(this._el("span", ["ml-2", "badge", "badge-secondary"], `${items.length}`));
		section.appendChild(header);

		const grid = this._el("div", ["bd-grid"]);
		items.forEach((item, i) => grid.appendChild(this._render_card(item, i)));
		section.appendChild(grid);

		this.sections_wrapper.appendChild(section);
	}

	_render_card(item, index) {
		const card = this._el("div", ["bd-card"]);
		card.style.animationDelay = `${index * 40}ms`;
		card.addEventListener("click", () => frappe.set_route("Form", item.doctype, item.name));

		const top = this._el("div", ["d-flex", "align-items-center", "justify-content-between", "mb-2"]);
		top.appendChild(this._el("span", ["indicator-pill", item.color], item.status));
		card.appendChild(top);

		const label = this._el("div", ["font-weight-bold", "text-truncate"], item.label);
		label.title = item.label;
		card.appendChild(label);

		return card;
	}

	_get_indicator_color(status) {
		const map = { "Completed": "green", "Analysis Completed": "green", "Closed": "red" };
		return map[status] || "orange";
	}

	_el(tag, classes = [], text = "") {
		const el = document.createElement(tag);
		if (classes.length) el.classList.add(...classes);
		if (text) el.textContent = text;
		return el;
	}
};