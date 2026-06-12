// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bank Transaction", {
	refresh(frm) {
		etransactions.accounting_hub.add_request_buttons(frm);
	},
});
