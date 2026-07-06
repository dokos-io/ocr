// Copyright (c) 2024, Dokos SAS and contributors
// For license information, please see license.txt

frappe.provide("ocr.pending_invoice");
frappe.provide("ocr.ui")

frappe.ui.form.on("Pending Purchase Invoice", {
	onload(frm) {
		frappe.call({
			method: "ocr.ocr.doctype.pending_purchase_invoice.pending_purchase_invoice.get_settings"
		}).then(r => {
			frm.toggle_display("select_purchase_orders", !r.message?.reconcile_with_purchase_receipts)
		})
	},
	setup(frm) {
		frm.set_query("expense_account", "items", function(doc) {
			return {
				filters: {
					"company": doc.company,
					"report_type": "Profit and Loss",
					"is_group": 0
				}
			};
		});

		frm.set_query("item_code", "items", function(doc) {
			return {
				query: "erpnext.controllers.queries.item_query",
				filters: { 'supplier': frm.doc.supplier, 'is_purchase_item': 1, 'has_variants': 0}
			}
		});

		frm.set_query("taxes_and_charges", function(doc) {
			return {
				filters: {
					"company": doc.company,
					"disabled": 0,
				}
			};
		});

		$(frm.wrapper).on("dirty", function () {
			frm.trigger("set_bottom_button_label");
		})

		frm.set_query("item_tax_template", "items", function(doc, cdt, cdn) {
			return set_query_for_item_tax_template(doc, cdt, cdn);
		});
	},

	async set_bottom_button_label(frm) {
		let label = __("Save")
		if (!frm.is_dirty()) {
			const items_not_linked_to_po = await items_are_not_linked_to_purchase_document(frm);
			label = items_not_linked_to_po ? __("Create Purchase Order") : __("Create Purchase Invoice")
		}
		frm.get_field("create_purchase_invoice").set_label(label);
	},

	refresh(frm) {

		if (frm.is_new() || ["Completed", "Closed"].includes(frm.doc.status)) {
			frm.set_read_only();
		}

		frm.trigger("show_preview");
		frm.trigger("set_bottom_button_label");
		frm.trigger("compare_totals");

		try { 
			$('[data-fieldname="data_column"]').removeClass("col-sm-6").addClass("col-sm-4")
			$('[data-fieldname="preview_column"]').removeClass("col-sm-6").addClass("col-sm-8")
			frm.get_field("create_purchase_invoice").$wrapper.addClass("text-right")
			frm.get_field("create_purchase_invoice").$wrapper.parent().parent().addClass("mt-auto")
			$('[data-fieldname="create_purchase_invoice"] button').addClass("btn-primary")
		} catch(err) {
			console.warn(e)
		}

		if (frm.doc.status != "Closed" && frappe.perm.has_perm(frm.doctype, 1, "write")) {
			frm.add_custom_button(__('Close'), function() {
				frm.call("close_request").then(() => { frm.reload_doc() });
			}, __("Actions"));
		} else {
			frm.add_custom_button(__('Reopen'), function() {
				frm.call("open_request").then(() => { frm.reload_doc() });
			}, __("Actions"));
		}

		frm.trigger("check_tax_id");
		frm.trigger("check_supplier_id");
		frm.trigger("check_po_exists");
		frm.trigger("add_credit_note_allocation_button");
		frm.trigger("add_create_debit_note_button");
		frm.trigger("render_credit_note_allocation_recap");
	},

	add_credit_note_allocation_button(frm) {
		if (frm.is_new() || !frm.doc.is_return) return;
		if (["Completed", "Closed"].includes(frm.doc.status)) return;

		frm.add_custom_button(__("Credit note allocation"), function() {
			open_credit_note_allocation_dialog(frm);
		}, __("Actions"));
	},

	add_create_debit_note_button(frm) {
		if (frm.is_new() || !frm.doc.is_return) return;
		if (["Completed", "Closed"].includes(frm.doc.status)) return;
		if (!(frm.doc.credit_note_allocations || []).length) return;

		frm.add_custom_button(__("Create debit note"), function() {
			// Persist the allocations + freshly built items before the server creates
			// and submits the debit note (which then auto-reconciles the allocations).
			if (frm.is_dirty()) {
				frm.save().then(() => create_purchase_invoice(frm, true));
			} else {
				create_purchase_invoice(frm, true);
			}
		}, __("Actions")).addClass("btn-primary");
	},

	is_return(frm) {
		if (!frm.doc.is_return || frm.is_new() || !frm.doc.supplier) return;
		if (["Completed", "Closed"].includes(frm.doc.status)) return;
		open_credit_note_allocation_dialog(frm);
	},

	render_credit_note_allocation_recap(frm) {
		render_credit_note_allocation_recap(frm);
	},

	async show_preview(frm) {
		let $preview = "";
		await frappe.model.with_doc("File", frm.doc.file);
		const file_preview_field = frm.get_field("invoice_preview");
		try {
			const file_doc = frappe.model.get_doc("File", frm.doc.file);
			const file_url = file_doc.file_url.replace(/#/g, "%23")
			let file_extension = file_doc.file_type.toLowerCase();

			if (frappe.utils.is_image_file(file_doc.file_url)) {
				$preview = $(`<div class="img_preview">
					<img
						class="img-responsive"
						src="${frappe.utils.escape_html(file_url)}"
					/>
				</div>`);
			} else if (frappe.utils.is_video_file(file_doc.file_url)) {
				$preview = $(`<div class="img_preview">
					<video width="480" height="320" controls>
						<source src="${frappe.utils.escape_html(file_url)}">
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
							src="${frappe.utils.escape_html(file_url)}" type="application/pdf"
						>
					</object>
				</div>`);
			} else if (file_extension === "mp3") {
				$preview = $(`<div class="img_preview">
					<audio width="480" height="60" controls>
						<source src="${frappe.utils.escape_html(file_url)}" type="audio/mpeg">
						${__("Your browser does not support the audio element.")}
					</audio >
				</div>`);
			}

			if ($preview && file_preview_field.$wrapper.html() != $preview[0].outerHTML) {
				file_preview_field.$wrapper.html($preview);
			}
		} catch(e) {
			file_preview_field.$wrapper.html($preview);
			return;
		}
	},

	select_purchase_orders(frm) {
		new PurchaseDocumentSelector(frm, "Purchase Order")
	},

	select_purchase_receipts(frm) {
		new PurchaseDocumentSelector(frm, "Purchase Receipt")
	},

	create_purchase_invoice(frm) {
		if (frm.is_dirty()) {
			frm.scroll_set = true;
			frm.save();
			frm.get_field("create_purchase_invoice").set_label(__("Create Purchase Invoice"));
		} else {
			frappe.db.get_list("Purchase Invoice", {filters: {pending_purchase_invoice: frm.doc.name, docstatus: 0}}).then(draft_invoices => {
				if (draft_invoices.length) {
					confirm(__("A draft purchase invoice exists already for this pending purchase invoice."),
						[],
						(values) => { frappe.set_route("Form", "Purchase Invoice", draft_invoices[0].name); },
						(values) => { create_po_pi(frm) },
						__("Open the draft invoice"),
						__("Create a new invoice"),
					)
				} else {
					create_po_pi(frm)
				}
			})
		}
	},

	taxes_and_charges(frm) {
		frm.trigger("calculate_totals")
	},

	calculate_totals(frm) {
		frappe.call({
			method: "calculate_totals",
			doc: frm.doc,
		}).then((res) => {
			frm.refresh_field("net_total");
			frm.refresh_field("tax_total");
			frm.refresh_field("grand_total");
			frm.trigger("compare_totals");
		})
	},

	compare_totals(frm) {
		[["net_total", "supplier_net_amount"], ["tax_total", "supplier_tax_amount"], ["grand_total", "supplier_grand_total"]].map(field => {
			const ocr_value = frm.doc[field[1]] || 0.0;
			const user_value = frm.doc[field[0]] || 0.0;
			frm.get_field(field[0]).set_description("");
			if (user_value != ocr_value) {
				const diff = Math.abs(Math.abs(user_value) - Math.abs(ocr_value));
				if (diff) {
					frm.get_field(field[0]).set_description(`<span class='text-danger'>${__('Difference:')} ${format_currency(diff, frm.doc.currency)}</span>`);
				}

				if (frm.doc.items.length && diff && field[0] == "net_total") {
					frm.dashboard.set_headline(__("The net amount of the invoice and the selected purchase receipts don't match.<br>Please select another purchase receipt or adjust the unit rate to match the amount of this invoice."), "blue")
				}
			}
		})
	},

	supplier(frm) {
		erpnext.utils.get_party_details(frm);
	},

	tax_category(frm) {
		erpnext.utils.set_taxes(frm, "tax_category")
	},

	tax_id(frm) {
		frm.trigger("check_tax_id");
	},

	check_tax_id(frm) {
		frm.get_field("tax_id").set_description("")
		frm.toggle_display("update_supplier_tax_id", false);
		if (frm.doc.tax_id && frm.doc.supplier) {
			frappe.db.get_value("Supplier", frm.doc.supplier, "tax_id").then((supplier) => {
				if (!supplier.message.tax_id) {
					frm.toggle_display("update_supplier_tax_id", true);
					frm.get_field("tax_id").set_description(`<span class='text-info'>${__("Your supplier Tax ID is currently empty")}</span>`)
				} else if (frm.doc.tax_id != supplier.message.tax_id) {
					frm.toggle_display("update_supplier_tax_id", true);
					frm.get_field("tax_id").set_description(`<span class='text-info'>${__("Your supplier's current Tax ID is {0}", [supplier.message.tax_id])}<span>`)
				}
			})
		}
	},

	update_supplier_tax_id(frm) {
		if (frm.doc.tax_id) {
			frm.toggle_display("update_supplier_tax_id", false);
			frappe.db.set_value("Supplier", frm.doc.supplier, "tax_id", frm.doc.tax_id).then(() => {
				frm.trigger("check_tax_id");
			})
		}
	},

	create_supplier(frm) {
		if (frm.doc.tax_id && !frm.doc.supplier) {
			frappe.call({
				method: "erpnext.regional.france.extensions.supplier.company_query",
				args: {
					txt: frm.doc.tax_id
				}
			}).then((res) => {
				frappe.model.with_doctype("Supplier", () => {
					let new_doc = frappe.model.get_new_doc("Supplier");
					new_doc.tax_id = frm.doc.tax_id;
					if (res.message.length) {
						new_doc.supplier_name = res.message[0].label;
						new_doc.siren_number = frm.doc.tax_id.substring(4);
					}
					frappe.ui.form.make_quick_entry("Supplier", null, null, new_doc)
				});
			})
		}
	},
	check_supplier_id(frm) {
		if (frm.doc.purchase_order_number && frm.doc.supplier) {
			frappe.db.get_value("Purchase Order", frm.doc.purchase_order_number, "supplier", r => {
				if (r.supplier && r.supplier != frm.doc.supplier) {
					frm.dashboard.clear_headline();
					const msg = __("The selected supplier ({0}) is different from the purchase order supplier ({1})", [frm.doc.supplier, r.supplier])
					frm.dashboard.set_headline(msg, "red")
				}
			})
		}
	},
	check_po_exists(frm) {
		if (frm.doc.purchase_order_number) {
			frappe.db.get_value("Purchase Order", frm.doc.purchase_order_number, "name", r => {
				if (!r.name) {
					frm.dashboard.clear_headline();
					const msg = __("We are not able to find any purchase order with number {0}.", [frm.doc.purchase_order_number])
					frm.dashboard.set_headline(msg, "red")
				}
			})
		}
	},
});

const set_query_for_item_tax_template = (doc, cdt, cdn) => { // TODO: Handle through TransactionController ?
	const item = frappe.get_doc(cdt, cdn);
	if(!item.item_code) {
		return doc.company ? {filters: {company: doc.company}} : {};
	} else {
		let filters = {
			'item_code': item.item_code,
			'valid_from': ["<=", doc.transaction_date || doc.bill_date || doc.posting_date],
			'item_group': item.item_group,
			'doctype': doc.doctype, // @ dokos
			"base_net_rate": item.base_net_rate,
		}

		if (doc.tax_category)
			filters['tax_category'] = doc.tax_category;
		if (doc.company)
			filters['company'] = doc.company;

		return {
			query: "erpnext.controllers.queries.get_tax_template",
			filters: filters
		}
	}
}

const create_po_pi = async (frm) => {
	const items_not_linked_to_po = await items_are_not_linked_to_purchase_document(frm);
	if (items_not_linked_to_po) {
		confirm(__("Create a new purchase order with all item lines without purchase order ?"),
			[
				{
					"fieldtype": "Date",
					"fieldname": "transaction_date",
					"label": __("Purchase Order Date"),
					"default": frm.doc.bill_date
				}
			],
			(values) => { create_purchase_order(frm, values.transaction_date, true) },
			(values) => { create_purchase_order(frm, values.transaction_date, false) },
			__("Create and submit"),
			__("Create and keep in draft"),
		)
	} else {
		confirm(__("Create and submit a new purchase invoice ?"),
			[],
			(values) => { create_purchase_invoice(frm, true) },
			(values) => { create_purchase_invoice(frm, false) },
			__("Create and submit"),
			__("Create and keep in draft"),
		)
	}
}

const items_are_not_linked_to_purchase_document = async(frm) => {
	if (frm.doc.is_return) {
		return false;
	}

	no_purchase_order = await frappe.db.get_single_value("OCR Settings", "no_purchase_order")
	return no_purchase_order ? false : !!frm.doc.items.filter(i => !i.reference_doctype).length
}

const create_purchase_invoice = (frm, submit=false) => {
	frappe.show_alert("Purchase Invoice creation in progress")
	frappe.call({
		method: "ocr.ocr.doctype.pending_purchase_invoice.pending_purchase_invoice.create_purchase_invoice",
		args: {
			docname: frm.doc.name,
			submit: submit
		}
	}).then((res) => {
		frm.reload_doc();
		if (submit && res.message.docstatus == 0) {
			frappe.open_in_new_tab = true;
			frappe.set_route("Form", res.message.doctype, res.message.name);
		} else {
			const success_action = new ocr.ui.SuccessAction(frm, __("Purchase invoice created"), "Purchase Invoice", res.message.name)
			success_action.show();
		}
	})
}


const create_purchase_order = (frm, transaction_date, submit=false) => {
	frappe.show_alert("Purchase Order creation in progress")
	frappe.call({
		method: "ocr.ocr.doctype.pending_purchase_invoice.pending_purchase_invoice.create_purchase_order",
		args: {
			docname: frm.doc.name,
			submit: submit,
			transaction_date: transaction_date
		}
	}).then((res) => {
		frm.reload_doc();
		const success_action = new ocr.ui.SuccessAction(frm, __("Purchase order created"), "Purchase Order", res.message.name)
		success_action.show();
	})
}

const confirm = (message, fields, confirm_action, reject_action, confirm_title, reject_title) => {
	var d = new frappe.ui.Dialog({
		title: __("Confirm", null, "Title of confirmation dialog"),
		fields: fields,
		primary_action_label: confirm_title || __("Yes", null, "Approve confirmation dialog"),
		primary_action: () => {
			const values = d.get_values()
			confirm_action && confirm_action(values);
			d.hide();
		},
		secondary_action_label: reject_title || __("No", null, "Dismiss confirmation dialog"),
		secondary_action: () => {
			const values = d.get_values()
			reject_action && reject_action(values);
			d.hide();
		}
	});

	d.$body.append(`<p class="frappe-confirm-message">${message}</p>`);
	d.show();

	// flag, used to bind "okay" on enter
	d.confirm_dialog = true;
	return d;
};


const credit_note_amount = (frm) => Math.abs(flt(frm.doc.supplier_net_amount));

const open_credit_note_allocation_dialog = async (frm) => {
	const currency = frm.doc.currency;
	const credit_amount = credit_note_amount(frm);

	let data;
	if (frm.doc.credit_note_allocations && frm.doc.credit_note_allocations.length) {
		data = frm.doc.credit_note_allocations.map(r => ({
			purchase_invoice: r.purchase_invoice,
			bill_no: r.bill_no,
			posting_date: r.posting_date,
			invoice_amount: r.invoice_amount,
			allocated_amount: r.allocated_amount,
		}));
	} else {
		const r = await frm.call("allocate_credit_note_fifo");
		data = (r.message || []).map(row => Object.assign({}, row));
	}

	const dialog = new frappe.ui.Dialog({
		title: __("Allocate credit note across invoices"),
		size: "large",
		fields: [
			{
				fieldname: "allocations",
				fieldtype: "Table",
				label: __("Invoices to allocate"),
				in_place_edit: true,
				cannot_add_rows: false,
				data: data,
				get_data: () => data,
				fields: [
					{
						fieldtype: "Link",
						fieldname: "purchase_invoice",
						options: "Purchase Invoice",
						label: __("Invoice"),
						in_list_view: 1,
						reqd: 1,
						columns: 3,
						get_query: () => ({
							// A debit note may be raised against an already-paid invoice,
							// so paid invoices (outstanding 0) stay selectable here.
							filters: {
								docstatus: 1,
								is_return: 0,
								company: frm.doc.company,
								supplier: frm.doc.supplier,
							},
						}),
						onchange: function() {
							const invoice = this.get_value();
							if (!invoice) return;
							const grid_row = this.grid_row;
							frappe.db.get_value("Purchase Invoice", invoice,
								["bill_no", "posting_date", "grand_total"]).then(res => {
								const v = res.message || {};
								grid_row.on_grid_fields_dict.bill_no?.set_value(v.bill_no || "");
								grid_row.on_grid_fields_dict.posting_date?.set_value(v.posting_date || "");
								grid_row.on_grid_fields_dict.invoice_amount?.set_value(v.grand_total || 0);
								update_comparator();
							});
						},
					},
					{ fieldtype: "Data", fieldname: "bill_no", label: __("Supplier Invoice No"), in_list_view: 1, read_only: 1, columns: 2 },
					{ fieldtype: "Date", fieldname: "posting_date", label: __("Posting Date"), read_only: 1 },
					{ fieldtype: "Currency", fieldname: "invoice_amount", label: __("Invoice Amount"), options: currency, in_list_view: 1, read_only: 1, columns: 2 },
					{
						fieldtype: "Currency",
						fieldname: "allocated_amount",
						label: __("Allocated"),
						options: currency,
						in_list_view: 1,
						columns: 2,
						onchange: function() { update_comparator(); },
					},
				],
			},
			{ fieldtype: "HTML", fieldname: "comparator" },
		],
		primary_action_label: __("Confirm allocation"),
		primary_action() {
			const rows = (dialog.fields_dict.allocations.df.data || [])
				.filter(r => r.purchase_invoice && flt(r.allocated_amount) > 0);
			frm.set_value("credit_note_allocations", []);
			rows.forEach(r => frm.add_child("credit_note_allocations", {
				purchase_invoice: r.purchase_invoice,
				bill_no: r.bill_no,
				posting_date: r.posting_date,
				invoice_amount: r.invoice_amount,
				allocated_amount: r.allocated_amount,
			}));
			frm.refresh_field("credit_note_allocations");
			dialog.hide();

			// Fill the debit-note item lines from the allocated invoices (scaled), like
			// the previous single-invoice flow, then surface the "Create debit note" action.
			frm.call("build_credit_note_items_from_allocations").then(r => {
				const res = r.message || {};
				frm.set_value("items", []);
				(res.items || []).forEach(it => frm.add_child("items", it));
				frm.refresh_field("items");
				if (res.currency) frm.set_value("currency", res.currency);
				frm.trigger("calculate_totals");
				render_credit_note_allocation_recap(frm);
				frm.trigger("add_create_debit_note_button");
			});
		},
	});

	const update_comparator = () => {
		const rows = dialog.fields_dict.allocations.df.data || [];
		let total = 0;
		rows.forEach(r => total += flt(r.allocated_amount));
		// Consistent with the form recap: show how much of the supplier net total has
		// been allocated, and only flag when the allocation goes above it.
		const over_allocated = total - credit_amount > 0.01;
		const pct = credit_amount ? Math.min(100, (total / credit_amount) * 100) : 0;
		const bar_color = over_allocated ? "var(--red-500, #dc3545)" : "var(--green-500, #28a745)";
		const pill = over_allocated
			? `<span class="indicator-pill red">${__("{0} over-allocated", [format_currency(total - credit_amount, currency)])}</span>`
			: "";

		dialog.fields_dict.comparator.$wrapper.html(`
			<div style="margin-top: 14px; padding: 14px 16px; background: var(--subtle-fg, #f4f5f6); border-radius: var(--border-radius-md, 8px);">
				<div style="height: 8px; border-radius: 6px; background: var(--gray-200, #e2e6e9); margin-bottom: 12px; overflow: hidden;">
					<div style="height: 100%; width:${pct}%; background-color:${bar_color}; border-radius: 6px; transition: width 0.2s ease;"></div>
				</div>
				<div class="d-flex justify-content-between align-items-center">
					<span class="text-muted">${__("Allocated")}: <b style="color: var(--text-color); font-variant-numeric: tabular-nums;">${format_currency(total, currency)}</b> ${__("of")} <b>${format_currency(credit_amount, currency)}</b></span>
					${pill}
				</div>
			</div>
		`);
	};

	dialog.show();
	update_comparator();
};

const render_credit_note_allocation_recap = (frm) => {
	const field = frm.get_field("credit_note_allocation_summary");
	if (!field) return;

	if (!frm.doc.is_return) {
		field.$wrapper.empty();
		return;
	}

	const rows = frm.doc.credit_note_allocations || [];
	const currency = frm.doc.currency;
	const supplier_net_total = Math.abs(flt(frm.doc.supplier_net_amount));
	const editable = !frm.is_new() && !["Completed", "Closed"].includes(frm.doc.status);

	const edit_button = editable
		? `<button class="btn btn-xs btn-default cn-alloc-edit-btn">
				<svg class="icon icon-xs"><use href="#icon-edit"></use></svg>
				${rows.length ? __("Edit") : __("Allocate")}
			</button>`
		: "";

	const bind_edit = () => {
		field.$wrapper.find(".cn-alloc-edit-btn").off("click").on("click", () => open_credit_note_allocation_dialog(frm));
	};

	if (!rows.length) {
		field.$wrapper.html(`
			<div class="d-flex justify-content-between align-items-center" style="padding: 10px 12px; border: 1px dashed var(--border-color, #ebeef0); border-radius: var(--border-radius-md, 8px); max-width: 540px; margin-bottom: 16px;">
				<span class="text-muted">${__("No credit note allocation yet.")}</span>
				${edit_button}
			</div>
		`);
		bind_edit();
		return;
	}

	let total = 0;
	const cell = "padding: 8px 12px; border-top: 1px solid var(--border-color, #ebeef0);";
	const body = rows.map(r => {
		total += flt(r.allocated_amount);
		return `<tr>
			<td style="${cell}">${frappe.utils.escape_html(String(r.purchase_invoice || ""))}</td>
			<td style="${cell} color: var(--text-muted);">${frappe.utils.escape_html(String(r.bill_no || ""))}</td>
			<td style="${cell} text-align: right; font-variant-numeric: tabular-nums;">${format_currency(r.allocated_amount, currency)}</td>
		</tr>`;
	}).join("");

	// Only flag when the allocation goes above the supplier net total; otherwise the
	// recap simply states how much of that total has been allocated.
	const over_allocated = total - supplier_net_total > 0.01;
	const badge = over_allocated
		? `<span class="indicator-pill red">${__("{0} over-allocated", [format_currency(total - supplier_net_total, currency)])}</span>`
		: "";

	const head = "padding: 8px 12px; font-weight: 500; color: var(--text-muted); border: none;";
	field.$wrapper.html(`
		<div style="border: 1px solid var(--border-color, #ebeef0); border-radius: var(--border-radius-md, 8px); overflow: hidden; max-width: 540px; margin-bottom: 16px;">
			<div class="d-flex justify-content-between align-items-center" style="padding: 8px 12px; border-bottom: 1px solid var(--border-color, #ebeef0);">
				<span style="font-weight: 600;">${__("Credit Note Allocation")}</span>
				${edit_button}
			</div>
			<table style="width: 100%; margin: 0; border-collapse: collapse; font-size: var(--text-sm, 13px);">
				<thead><tr style="background: var(--subtle-fg, #f4f5f6);">
					<th style="${head}">${__("Invoice")}</th>
					<th style="${head}">${__("Supplier Invoice No")}</th>
					<th style="${head} text-align: right;">${__("Allocated")}</th>
				</tr></thead>
				<tbody>${body}</tbody>
			</table>
			<div class="d-flex justify-content-between align-items-center" style="padding: 10px 12px; border-top: 1px solid var(--border-color, #ebeef0); background: var(--subtle-fg, #f4f5f6);">
				<span class="text-muted">${__("Allocated")}: <b style="color: var(--text-color); font-variant-numeric: tabular-nums;">${format_currency(total, currency)}</b> ${__("of")} <b>${format_currency(supplier_net_total, currency)}</b></span>
				${badge}
			</div>
		</div>
	`);
	bind_edit();
};


frappe.ui.form.on("Pending Purchase Invoice Item", {
	items_add(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "qty", 1);
		if (frm.doc.items.length == 1) {
			frappe.model.set_value(cdt, cdn, "qty", 1);
			frappe.model.set_value(cdt, cdn, "rate", frm.doc.supplier_net_amount || frm.doc.supplier_grand_total);
			frappe.model.set_value(cdt, cdn, "amount", frm.doc.supplier_net_amount || frm.doc.supplier_grand_total);
		}
	},
	item_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frappe.call({
			method: "ocr.ocr.doctype.pending_purchase_invoice.pending_purchase_invoice.get_item_details",
			args: {
				row: row,
				company: frm.doc.company,
				tax_category: frm.doc.tax_category
			}
		}).then((r) => {
			frappe.model.set_value(cdt, cdn, "cost_center", r.message?.cost_center || "");
			frappe.model.set_value(cdt, cdn, "expense_account", r.message?.expense_account || "");
			frappe.model.set_value(cdt, cdn, "description", r.message?.description || "");
			frappe.model.set_value(cdt, cdn, "item_tax_template", r.message?.item_tax_template || "");
		})
	},
	qty(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, "amount", row.qty * (row.rate || 0.0));
		frm.trigger("calculate_totals")
	},

	rate(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		frappe.model.set_value(cdt, cdn, "amount", row.qty * row.rate);
		frm.trigger("calculate_totals")
	},
})

class PurchaseDocumentSelector {
	constructor(frm, doctype) {
		this.frm = frm;
		this.doctype = doctype
		this.date_field = this.doctype == "Purchase Order" ? "transaction_date" : "posting_date"

		this.make_dialog()
	}

	make_dialog() {
		const multiselect_dialog = new frappe.ui.form.MultiSelectDialog({
			doctype: this.doctype,
			target: this.doctype,
			date_field: this.date_field,
			size: "extra-large",
			setters: [
				{
					fieldtype: "Link",
					options: "Supplier",
					label: __("Supplier"),
					fieldname: "supplier",
					default: this.frm.doc.supplier
				},
			],
			columns: ["name", "supplier", this.date_field, "grand_total", "status"],
			allow_child_item_selection: true,
			child_fieldname: "items",
			child_columns: ["supplier", this.date_field, "item_code", "qty", "net_amount", "cost_center"],
			add_filters_group: true,
			primary_action_label: __("Select one or more purchase orders"),
			get_query: () => {
				return {
					query: "ocr.ocr.doctype.pending_purchase_invoice.pending_purchase_invoice.get_purchase_documents",
					filters: {
						company: this.frm.doc.company,
						supplier: this.frm.doc.supplier,
						docstatus: 1,
						per_billed: ["<", 100.0],
						status: ["!=", "Closed"]
					},
				};
			},
			action: (selected_docs, args) => {
				if (selected_docs.length === 0) {
					frappe.msgprint(this.doctype == "Purchase Order" ? __("Please select at least one purchase order"): __("Please select at least one purchase receipt"));
					return;
				}

				const rows = multiselect_dialog.get_checked_items();
				if (!rows.every(row => row.supplier === rows[0].supplier)) {
					frappe.msgprint(this.doctype == "Purchase Order" ? __("Please select orders linked to the same supplier"): __("Please select receipts linked to the same supplier"));
					return;
				}

				frappe.call({
					method: "get_document_item_lines",
					doc: this.frm.doc,
					args: {
						doctype: this.doctype,
						selected_documents: selected_docs,
						allow_child_item_selection: args.allow_child_item_selection,
						filtered_line_items: args.filtered_children
					}
				}).then((res) => {
					if (res.message.company && !this.frm.doc.company) {
						this.frm.set_value("company", res.message.company)
					}

					if (res.message.supplier && !this.frm.doc.supplier) {
						this.frm.set_value("supplier", res.message.supplier)
					}

					if (res.message.currency && !this.frm.doc.currency) {
						this.frm.set_value("currency", res.message.currency)
					}

					res.message.items.map(r => {
						this.frm.add_child("items",
							{
								reference_doctype: this.doctype,
								reference_docname: r.parent,
								row: r.name,
								project: r.project,
								cost_center: r.cost_center,
								price: r.price,
								item_code: r.item_code,
								rate: r.rate,
								qty: r.qty,
								amount: r.amount,
								expense_account: r.expense_account,
								description: r.description,
							}
						)
						this.frm.refresh_field("items")
					})

					multiselect_dialog.dialog.hide();
				})
			}
		});

		multiselect_dialog.get_child_result = async () => {
			let filters = [["parentfield", "=", multiselect_dialog.child_fieldname]];

			await multiselect_dialog.add_parent_filters(filters);
			multiselect_dialog.add_custom_child_filters(filters);

			return frappe.call({
				method: "ocr.ocr.doctype.pending_purchase_invoice.pending_purchase_invoice.get_documents_child_items",
				args: {
					doctype: this.doctype,
					filters: filters,
					limit_page_length: multiselect_dialog.child_page_length + 5,
				},
			});
		}
	}
}


ocr.ui.SuccessAction = class SuccessAction {
	constructor(form, message, target_doctype, target_docname) {
		this.form = form;
		this.target_doctype = target_doctype;
		this.target_docname = target_docname;
		this.message = message || "";
		this.load_setting();
	}

	load_setting() {
		this.setting = {
			"message": this.message,
		}
	}

	show() {
		if (!this.setting) return;

		this.prepare_dom();
		this.show_alert();
	}

	prepare_dom() {
		this.container = $(document.body).find(".success-container");
		if (!this.container.length) {
			this.container = $('<div class="success-container">').appendTo(document.body);
		}
	}

	show_alert() {
		const $buttons = this.get_actions().map((action) => {
			const $btn = $(
				`<button class="next-action"><span>${__(action.label)}</span></button>`
			);
			$btn.click(() => action.action(this.form));
			return $btn;
		});

		const next_action_container = $(`<div class="next-action-container"></div>`);
		next_action_container.append($buttons);
		const html = next_action_container;

		frappe.show_alert(
			{
				message: this.setting.message,
				body: html,
				indicator: "green",
			},
			7
		);
	}

	get_actions() {
		const actions = [];
		const checked_actions = ["email", "view", "next", "list"];
		checked_actions.forEach((action) => {
			actions.push(this.default_actions[action]);
		});

		return actions;
	}

	get default_actions() {
		return {
			view: {
				label: __("View {}", [__(this.target_doctype)]),
				action: (frm) => {
					frappe.set_route("Form", this.target_doctype, this.target_docname);
				},
			},
			next: {
				label: __("Next"),
				action: (frm) => frm.navigate_records(0),
			},
			email: {
				label: __("Email"),
				action: (frm) => frm.email_doc(),
			},
			list: {
				label: __("Back to list"),
				action: (frm) => {
					frappe.set_route("List", this.target_doctype);
				},
			},
		};
	}
};
