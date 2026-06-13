// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("Journal Entry", {
	refresh(frm) {
		etransactions.hub.add_request_buttons(frm);
	},
});
