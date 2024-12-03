frappe.provide("ocr.ocr_dashboard");

ocr.ocr_dashboard.MatchTab = class MatchTab {
	constructor(opts) {
		$.extend(this, opts);
		this.make();
	}

	async make() {
		this.panel_manager.actions_tab = "match_voucher-tab";

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

		this.bind_row_check_event();
	}

	set_table_data(vouchers) {
		this.summary_data = {};
		let table_data = vouchers.map((row) => {
			return [
				{
					content: row.doctype,
					format: (value) => {
						return __(value);
					}
				},
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
						return value + " %";
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

		const reference_doctype = row.filter(r => r.column.id == "reference_doctype")[0].content;
		const document_name = row.filter(r => r.column.id == "document_name")[0].content;
		frappe.model.with_doctype(`${reference_doctype} Item`).then(() => {
			const meta = frappe.get_meta(`${reference_doctype} Item`);
			this.match_field_group.fields_dict.items.grid.df.fields =  meta.fields;

			frappe.model.with_doc(reference_doctype, document_name).then(() => {
				const doc = frappe.get_doc(reference_doctype, document_name);
				this.match_field_group.fields_dict.items.grid.df.get_data = () => {
					return doc.items.map(i => {
						return {...i, parent: null, parenttype: null, name: null, __islocal: true}
					});
				};
				this.match_field_group.fields_dict.vouchers_section.hide();
				this.match_field_group.fields_dict.items.toggle(true);
				this.match_field_group.refresh();
				this.match_field_group.fields_dict.items.grid.refresh();
			})
		});
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
				fieldtype: "Section Break",
				fieldname: "vouchers_section"
			},
			{
				fieldname: "vouchers",
				fieldtype: "HTML",
			},
			{
				fieldtype: "Section Break"
			},
			{
				fieldname: "items",
				fieldtype: "Table",
				fields: [],
				hidden: 1
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
				name: __("Reference DocType"),
				id: "reference_doctype",
				editable: false,
				hidden: true
			},
			{
				name: __("Document Name"),
				id: "document_name",
				editable: false,
			},
			{
				name: __("Supplier"),
				id: "supplier",
				editable: false,
			},
			{
				name: __("Date"),
				id: "date",
				editable: false,
			},
			{
				name: __("Net Total"),
				id: "net_total",
				editable: false,
			},
			{
				name: __("Grand Total"),
				id: "grand_total",
				editable: false,
			},
			{
				name: __("Billed %"),
				id: "per_billed",
				editable: false,
			},
		];
	}
}