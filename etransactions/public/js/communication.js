frappe.ui.form.on("Communication", {
	refresh(frm) {
		if(frm.doc.communication_medium == "Email" && frm.doc.sent_or_received == "Received") {
			frm.events.setup_ocr_buttons(frm);
		}
	},

	setup_ocr_buttons(frm) {

		if(frm.doc.reference_doctype != "OCR Purchase Invoice Basket") {
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
		frm.events.create_basket(frm, "Purchase Invoice");
	},

	create_basket_for_expense: (frm) => {
		frm.events.create_basket(frm, "Expense");
	},

	create_basket: (frm, basket_type) => {
		return frappe.call({
			method: "etransactions.etransactions.doctype.ocr_purchase_invoice_basket.ocr_purchase_invoice_basket.make_basket_from_communication",
			args: {
				communication: frm.doc.name,
				basket_type: basket_type
			},
			freeze: true,
			callback: (r) => {
				console.log(r)
				if(r.message) {
					frm.reload_doc()
				}
			}
		})
	}
})