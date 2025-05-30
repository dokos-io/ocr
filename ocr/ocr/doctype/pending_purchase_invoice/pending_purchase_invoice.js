// Copyright (c) 2024, Dokos SAS and contributors
// For license information, please see license.txt

frappe.provide("ocr.pending_invoice");
frappe.provide("ocr.ui")

frappe.ui.form.on("Pending Purchase Invoice", {
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

		frm.set_query("original_invoice", function(doc) {
			return {
				filters: {
					"is_return": false,
					"company": frm.doc.company,
				}
			};
		});

		$(frm.wrapper).on("dirty", function () {
			frm.trigger("set_bottom_button_label");
		})
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

		if (frm.doc.status != "Closed") {
			frm.add_custom_button(__('Close'), function() {
				frm.call("close_request").then(() => { frm.reload_doc() });
			}, __("Actions"));
		} else {
			frm.add_custom_button(__('Reopen'), function() {
				frm.call("open_request").then(() => { frm.reload_doc() });
			}, __("Actions"));
		}

		frm.trigger("check_tax_id")

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
						() => { frappe.set_route("Form", "Purchase Invoice", draft_invoices[0].name); },
						() => { create_po_pi(frm) },
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
					frm.get_field(field[0]).set_description(`<span class='text-danger'>${__('Difference:')} ${format_currency(diff, 'EUR')}</span>`);
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
	original_invoice(frm) {
		if (frm.doc.original_invoice) {
			frappe.call({
				method: "get_return_invoice",
				doc: frm.doc,
				args: {
					original_invoice: frm.doc.original_invoice
				}
			}).then(r => {
				frm.set_value("items", []);
				r.message.items.map(i => {
					frm.add_child("items",
						{
							row: i.name,
							project: i.project,
							cost_center: i.cost_center,
							price: i.price,
							item_code: i.item_code,
							description: i.description,
							rate: i.rate,
							qty: i.qty,
							amount: i.amount,
							expense_account: i.expense_account
						}
					)
				})
				frm.refresh_field("items")

				["currency", "department", "cost_center"].forEach(f => {
					if (r.message[f]) {
						frm.set_value(f, r.message[f])
					}
				})
			})
		}
	}
});

const create_po_pi = async (frm) => {
	const items_not_linked_to_po = await items_are_not_linked_to_purchase_document(frm);
	if (items_not_linked_to_po) {
		confirm(__("Create a new purchase order with all item lines without purchase order ?"),
			() => { create_purchase_order(frm, true) },
			() => { create_purchase_order(frm, false) },
			__("Create and submit"),
			__("Create and keep in draft"),
		)
	} else {
		confirm(__("Create and submit a new purchase invoice ?"),
			() => { create_purchase_invoice(frm, true) },
			() => { create_purchase_invoice(frm, false) },
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


const create_purchase_order = (frm, submit=false) => {
	frappe.show_alert("Purchase Order creation in progress")
	frappe.call({
		method: "ocr.ocr.doctype.pending_purchase_invoice.pending_purchase_invoice.create_purchase_order",
		args: {
			docname: frm.doc.name,
			submit: submit
		}
	}).then((res) => {
		frm.reload_doc();
		const success_action = new ocr.ui.SuccessAction(frm, __("Purchase order created"), "Purchase Order", res.message.name)
		success_action.show();
	})
}

const confirm = (message, confirm_action, reject_action, confirm_title, reject_title) => {
	var d = new frappe.ui.Dialog({
		title: __("Confirm", null, "Title of confirmation dialog"),
		primary_action_label: confirm_title || __("Yes", null, "Approve confirmation dialog"),
		primary_action: () => {
			confirm_action && confirm_action();
			d.hide();
		},
		secondary_action_label: reject_title || __("No", null, "Dismiss confirmation dialog"),
		secondary_action: () => {
			reject_action && reject_action();
			d.hide();
		}
	});

	d.$body.append(`<p class="frappe-confirm-message">${message}</p>`);
	d.show();

	// flag, used to bind "okay" on enter
	d.confirm_dialog = true;
	return d;
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
				item_code: row.item_code,
				company: frm.doc.company
			}
		}).then((r) => {
			frappe.model.set_value(cdt, cdn, "cost_center", r.message?.cost_center || "");
			frappe.model.set_value(cdt, cdn, "expense_account", r.message?.expense_account || "");
			frappe.model.set_value(cdt, cdn, "description", r.message?.description || "");
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
