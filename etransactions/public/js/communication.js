frappe.ui.form.on("Communication", {
	refresh(frm) {
		if(frm.doc.communication_medium == "Email" && frm.doc.sent_or_received == "Received") {
			frm.events.setup_ocr_buttons(frm);
		}
	},

	setup_ocr_buttons(frm) {

		if(frm.doc.reference_doctype != "Supplier Invoices Basket") {
			let confirm_msg = __("Are you sure you want to create {0} from this email ?");

			frm.add_custom_button(
				__("Purchase Invoice"),
				() => {
					frappe.confirm(__(confirm_msg, [__("Purchase Invoice")]), () => {
						frm.trigger("create_basket_for_purchase_invoice");
					})
				},
				__("Create")
			);

			// frm.add_custom_button(
			// 	__("Expense"),
			// 	() => {
			// 		frappe.confirm(__(confirm_msg, [__("Expense")]), () => {
			// 			frm.trigger("create_basket_for_expense");
			// 		})
			// 	},
			// 	__("Create")
			// );
		}
	},

	create_basket_for_purchase_invoice: (frm) => {
		frm.events.create_basket(frm);
	},

	create_basket_for_expense: (frm) => {
		frm.events.create_basket(frm);
	},

	create_basket: (frm) => {
		return frappe.call({
			method: "etransactions.etransactions.doctype.supplier_invoices_basket.supplier_invoices_basket.make_basket_from_communication",
			args: {
				communication: frm.doc.name
			},
			freeze: true,
			callback: (r) => {
				if(r.message) {
					frm.reload_doc()
				}
			}
		})
	}
})