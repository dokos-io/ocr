frappe.listview_settings["Supplier Invoice"] = {
	hide_name_column: true,
	onload: function (listview) {
		listview.page.add_inner_button(__("Upload Invoices"), function () {
			new frappe.ui.FileUploader({
				make_attachments_public: false,
				on_success: (file_doc) => {
					frappe.call({
						method: "etransactions.etransactions.doctype.supplier_invoices_basket.supplier_invoices_basket.create_basket_from_files",
						args: {
							file_names: [file_doc.name],
						}
					}).then(r => {
						if (r.message) {
							frappe.show_alert(
								__("Basket created"),
								5
							);
						}
					})
				},
			});
		}, null, "primary");

		listview.page.add_menu_item(__("Retry Supplier Match"), () => {
			const pending = listview.get_checked_items();

			if (!pending.length) {
				frappe.show_alert({ message: __("No unmatched invoices selected"), indicator: "orange" }, 4);
				return;
			}
			frappe.call({
				method: "etransactions.etransactions.doctype.supplier_invoice.supplier_invoice.retry_supplier_match",
				args: { invoices: pending.map(d => d.name) },
				freeze: true,
				freeze_message: __("Retrying supplier match…"),
			}).then(r => {
				const count = r.message || 0;
				frappe.show_alert({
					message: count
						? __("{0} of {1} invoice(s) matched", [count, pending.length])
						: __("No new matches found"),
					indicator: count > 0 ? "green" : "orange",
				}, 5);
				listview.refresh();
			});
		});

		listview.etransactions_dashboard = new SupplierInvoiceDashboard(listview);
	},

	refresh: function (listview) {
		listview.etransactions_dashboard.refresh();
	},
};

class SupplierInvoiceDashboard {
	constructor(list_view) {
		this.list_view = list_view;
		const page_toolbars = list_view.parent.getElementsByClassName("page-toolbar");
		if (!page_toolbars.length) return;
		this.page_toolbar = page_toolbars[0];
	}

	refresh() {
		this.build();
	}

	async build() {
		await this.get_data();
		this.page_toolbar.innerHTML = "";

		const dashboard_container = document.createElement("div");
		dashboard_container.classList.add("list-dashboard", "pb-4", "w-100");
		this.page_toolbar.appendChild(dashboard_container);

		const cards = [
			{
				label: __("Uploads Pending Analysis", null, "Supplier Invoice List"),
				count: this.basket_count,
				icon: "inbox",
				color: this.basket_count > 0 ? "var(--yellow-500)" : "var(--gray-500)",
				bg: this.basket_count > 0 ? "var(--yellow-100)" : "var(--bg-light-gray)",
				action: () => frappe.set_route("List", "Supplier Invoices Basket", {
					status: ["in", ["Not Started", "In Progress"]],
				}),
			},
			{
				label: __("OCR In Progress", null, "Supplier Invoice List"),
				count: this.ocr_count,
				icon: "setting",
				color: this.ocr_count > 0 ? "var(--blue-500)" : "var(--gray-500)",
				bg: this.ocr_count > 0 ? "var(--blue-100)" : "var(--bg-light-gray)",
				action: () => frappe.set_route("List", "OCR Request", {
					status: ["in", ["Analysis Completed", "Error"]],
				}),
			},
		];

		cards.forEach((card_settings) => {
			const card = document.createElement("div");
			card.classList.add("dashboard-card");
			card.style.setProperty("--card-color", card_settings.color);
			card.style.setProperty("--card-bg-color", card_settings.bg);
			card.onclick = card_settings.action;

			const icon_wrapper = document.createElement("div");
			icon_wrapper.classList.add("icon-wrapper");
			icon_wrapper.innerHTML = frappe.utils.icon(card_settings.icon, "lg");

			const text_content = document.createElement("div");
			text_content.classList.add("text-content");

			const label = document.createElement("div");
			label.classList.add("label");
			label.innerText = card_settings.label;

			const value = document.createElement("div");
			value.classList.add("value");
			value.innerText = card_settings.count;

			text_content.appendChild(label);
			text_content.appendChild(value);
			card.appendChild(icon_wrapper);
			card.appendChild(text_content);
			dashboard_container.appendChild(card);
		});

		this.page_toolbar.classList.remove("hide");
	}

	async get_data() {
		[this.basket_count, this.ocr_count] = await Promise.all([
			frappe.db.count("Supplier Invoices Basket", {
				filters: [["status", "in", ["Not Started", "In Progress"]]],
			}),
			frappe.db.count("OCR Request", {
				filters: [["status", "in", ["Pending", "Error"]]],
			}),
		]);
	}
}
