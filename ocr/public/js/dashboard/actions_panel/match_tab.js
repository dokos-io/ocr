frappe.provide("ocr.ocr_dashboard");

ocr.ocr_dashboard.MatchTab = class MatchTab {
	constructor(opts) {
		$.extend(this, opts);
		this.make();
	}

	async make() {
		this.panel_manager.actions_tab = "match_voucher-tab";
		console.log(this.actions_panel.$tab_content)
		this.match_field_group = new frappe.ui.FieldGroup({
			fields: this.get_match_tab_fields(),
			body: this.actions_panel.$tab_content,
			card_layout: true,
		});
		this.match_field_group.make()

		await this.populate_matching_vouchers();
	}


	async populate_matching_vouchers(event_obj) {
		if (event_obj && event_obj.type === "input") {
			// `bind_change_event` in `data.js` triggers both an input and change event
			// This triggers the `populate_matching_vouchers` twice on clicking on filters
			// Since the input event is debounced, we can ignore it for a checkbox
			return;
		}

		this.render_data_table();
		this.actions_table.freeze();

		let filter_fields = this.match_field_group.get_values();
		let document_types = Object.keys(filter_fields).filter(field => filter_fields[field] === 1);

		this.update_filters_in_state(document_types);

		let vouchers = await this.get_matching_vouchers(document_types);
		console.log(vouchers)
		this.set_table_data(vouchers);
		this.actions_table.unfreeze();
	}

	update_filters_in_state(document_types) {
		Object.keys(this.panel_manager.actions_filters).map((key) => {
			let value = document_types.includes(key) ? 1 : 0;
			this.panel_manager.actions_filters[key] = value;
		})
	}

	async get_matching_vouchers(document_types) {
		console.log(this)
		let vouchers = await frappe.call({
			method:
				"ocr.ocr.doctype.ocr_reconciliation_dashboard.ocr_reconciliation_dashboard.get_matching_documents",
			args: {
				ocr_request: this.transaction.name,
				document_types: document_types,
				filter_by_reference_date: this.doc.filter_by_reference_date,
				from_reference_date: this.doc.from_reference_date,
				to_reference_date: this.doc.to_reference_date
			},
		}).then(result => result.message);
		return vouchers || [];
	}

	render_data_table() {
		const datatable_options = {
			columns: this.get_data_table_columns(),
			data: [],
			dynamicRowHeight: true,
			checkboxColumn: true,
			inlineFilters: true,
			layout: "fluid",
			serialNoColumn: false,
			freezeMessage: __("Loading..."),
		};

		this.actions_table = new frappe.DataTable(
			this.match_field_group.get_field("vouchers").$wrapper[0],
			datatable_options
		);

		// Highlight first row
		this.actions_table.style.setStyle(
			".dt-cell[data-row-index='0']", { backgroundColor: '#F4FAEE' }
		);

		// this.bind_row_check_event();
	}

	set_table_data(vouchers) {
		this.summary_data = {};
		let table_data = vouchers.map((row) => {
			return [
				{
					content: row.name || '',
					format: (value) => {
						return value;
					}
				},
				{
					content: row.supplier,
					format: () => {
						if (row.supplier) {
							frappe.utils.add_link_title("Supplier", row.supplier, row.supplier_name);
						}
						let formatted_value = frappe.format(row.supplier, { fieldtype: "Link", options: "Supplier" });
						return formatted_value;
					}
				},
				{
					content: row.transaction_date || row.posting_date, // Reference Date
					format: (value) => {
						const formatted_date = frappe.format(value, { fieldtype: "Date" });
						return row.date_match ? formatted_date.bold() : formatted_date;
					}
				},
				{
					content: row.net_total,
					format: (value) => {
						let formatted_value = format_currency(value, row.currency);
						return formatted_value;
					}
				},
				{
					content: row.grand_total,
					format: (value) => {
						let formatted_value = format_currency(value, row.currency);
						return formatted_value;
					}
				},
				{
					content: row.per_billed,
					format: (value) => {
						console.log(value)
						return value;
					},
				},
			];
		});

		this.actions_table.refresh(table_data, this.get_data_table_columns());
	}

	bind_row_check_event() {
		// Resistant to row removal on being out of view in datatable
		$(this.actions_table.bodyScrollable).on("click", ".dt-cell__content input", (e) => {
			let idx = $(e.currentTarget).closest(".dt-cell").data().rowIndex;
			let voucher_row = this.actions_table.getRows()[idx];

			this.check_data_table_row(voucher_row)
		})
	}

	check_data_table_row(row) {
		if (!row) return;

		let id = row[5].content;  // Voucher name
		let value = this.get_amount_from_row(row);

		// If `id` in summary_data, remove it (row was unchecked), else add it
		if (id in this.summary_data) {
			delete this.summary_data[id];
		} else {
			this.summary_data[id] = value;
		}

		// Total of selected row amounts in summary_data
		// Cap total_allocated to unallocated amount
		let total_allocated = Object.values(this.summary_data).reduce(
			(a, b) => a + b, 0
		);
		let max_allocated = Math.min(total_allocated, this.transaction.unallocated_amount);
	}


	get_match_tab_fields() {
		const filters_state = this.panel_manager.actions_filters;
		return [
			{
				label: __("Purchase Orders"),
				fieldname: "purchase_order",
				fieldtype: "Check",
				default: filters_state.purchase_order,
				onchange: (e) => {
					this.populate_matching_vouchers(e);
				}
			},
			{
				fieldtype: "Column Break"
			},
			// {
			// 	label: __("Purchase Receipts"),
			// 	fieldname: "purchase_receipt",
			// 	fieldtype: "Check",
			// 	default: filters_state.purchase_receipt,
			// 	onchange: (e) => {
			// 		this.populate_matching_vouchers(e);
			// 	}
			// },
			{
				fieldtype: "Section Break"
			},
			{
				fieldname: "vouchers",
				fieldtype: "HTML",
			},
			// {
			// 	label: __("Reconcile"),
			// 	fieldname: "bt_reconcile",
			// 	fieldtype: "Button",
			// 	primary: true,
			// 	click: () => {
			// 		this.reconcile_selected_vouchers();
			// 	}
			// },
		];
	}

	get_data_table_columns() {
		return [
			{
				name: __("ID"),
				editable: false,
			},
			{
				name: __("Supplier"),
				editable: false,
			},
			{
				name: __("Date"),
				editable: false,
			},
			{
				name: __("Net Total"),
				editable: false,
			},
			{
				name: __("Grand Total"),
				editable: false,
			},
			{
				name: __("Billed %"),
				editable: false,
			},
		];
	}

	get_amount_from_row(row) {
		return row[2].content;  // Amount
	}
}