frappe.provide("ocr.ocr_dashboard");

ocr.ocr_dashboard.DashboardManager = class DashboardManager {
	constructor(opts) {
		Object.assign(this, opts);
		this.make();
	}

	make() {
		this.render_dashboard();
	}

	async render_dashboard() {
		this.pending_invoices = await this.get_pending_invoices();

		this.$wrapper.empty();
		this.$panel_wrapper = this.$wrapper.append(`
			<div class="panel-container d-flex"></div>
		`).find(".panel-container");

		this.render_panels()
	}

	async get_pending_invoices() {
		let pending_invoices = await frappe.call({
			method:
				"ocr.ocr.doctype.ocr_reconciliation_dashboard.ocr_reconciliation_dashboard.get_pending_invoices",
			args: {
				company: this.doc.company,
				// from_date: this.doc.bank_statement_from_date,
				// to_date: this.doc.bank_statement_to_date,
				order_by: this.order || "creation desc",
			},
			freeze: true,
			freeze_message: __("Fetching Bank Transactions"),
		}).then(response => response.message);
		return pending_invoices;
	}

	render_panels() {
		this.set_actions_panel_default_states();

		if (!this.pending_invoices || !this.pending_invoices.length) {
			this.render_no_transactions();
		} else {
			this.render_list_panel();

			let first_invoice = this.pending_invoices[0];
			this.$list_container.find("#" + first_invoice.name).click();
		}
	}

	set_actions_panel_default_states() {
		// Init actions panel states to store for persistent views
		this.actions_tab = "details-tab";
		this.actions_filters = {
			purchase_order: 1,
			purchase_receipt: 0,
		}
	}

	render_no_transactions() {
		this.$panel_wrapper.empty();
		this.$panel_wrapper.append(`
			<div class="no-transactions">
				<img src="/assets/frappe/images/ui-states/list-empty-state.svg" alt="Empty State">
				<p>${__("No more pending invoices to reconcile.")}</p>
			</div>
		`);
	}

	render_list_panel() {
		this.$panel_wrapper.append(`
			<div class="list-panel">
				<div class="sort-by"></div>
				<div class="list-container"></div>
			</div>
		`);

		this.render_sort_area();
		this.render_pending_invoices_list();
	}

	render_actions_panel() {
		this.actions_panel =  new ocr.ocr_dashboard.ActionsPanelManager({
			$wrapper: this.$panel_wrapper,
			transaction: this.active_transaction,
			doc: this.doc,
			panel_manager: this
		});
	}

	render_sort_area() {
		this.$sort_area = this.$panel_wrapper.find(".sort-by");
		this.$sort_area.append(`
			<div class="sort-by-title"> ${__("Sort By")} </div>
			<div class="sort-by-selector p-10"></div>
		`);

		var me = this;
		new frappe.ui.SortSelector({
			parent: me.$sort_area.find(".sort-by-selector"),
			args: {
				sort_by: me.order_by || "creation",
				sort_order: me.order_direction || "desc",
				options: [
					{fieldname: "creation", label: __("Creation Date")},
				]
			},
			change: function(sort_by, sort_order) {
				// Globally set the order used in the re-rendering of the list
				me.order_by = (sort_by || me.order_by || "creation");
				me.order_direction = (sort_order || me.order_direction || "desc");
				me.order =  me.order_by + " " + me.order_direction;

				// Re-render the list
				me.render_dashboard();
			}
		});
	}

	render_pending_invoices_list() {
		this.$list_container = this.$panel_wrapper.find(".list-container");

		this.pending_invoices.map(invoice => {
			let $row = this.$list_container.append(`
				<div id="${invoice.name}" class="transaction-row p-10">
					<div class="d-flex">
						<div class="w-50 text-left">
							<div
								title="${__("Supplier")}"
								class="account-holder ${invoice.supplier ? '' : 'hide'}"
							>
								<span class="account-holder-value">${invoice.supplier}</span>
							</div>

							<div class="bt-amount-container mt-2">
								<span
									title="${__("Amount")}"
									class="bt-amount"
								>
									<b>${format_currency(invoice.grand_total, invoice.currency)}</b>
								</span>
							</div>
						</div>

						<div class="w-50 text-right">
							<div>
								<span class="indicator-pill blue">${__(invoice.status)}</span>
							</div>
							<div class="mt-2">
								<span title="${__("Date")}">${frappe.format(invoice.bill_date || invoice.creation, { fieldtype: "Date" })}</span>
							</div>

						</div>

					</div>
				</div>
			`).find("#" + invoice.name);

			$row.on("click", () => {
				$row.addClass("active").siblings().removeClass("active");

				// this.transaction's objects get updated, we want the latest values
				this.active_transaction = this.pending_invoices.find(({name}) => name === invoice.name);
				this.render_actions_panel();
			})
		})
	}
}