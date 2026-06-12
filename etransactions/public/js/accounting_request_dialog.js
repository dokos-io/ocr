// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt

frappe.provide("etransactions.accounting_hub");

etransactions.accounting_hub.make_accounting_request = function (frm, request_type) {
	const dialog = new frappe.ui.Dialog({
		title: __("New Accounting Request"),
		fields: [
			{
				fieldname: "subject",
				fieldtype: "Data",
				label: __("Subject"),
				reqd: 1,
				default: __("{0}: {1}", [__(request_type), frm.docname]),
			},
			{
				fieldname: "request_type",
				fieldtype: "Select",
				label: __("Request Type"),
				options: ["Missing Justificative", "Question", "Correction Needed", "Information"],
				default: request_type,
				reqd: 1,
			},
			{
				fieldname: "assign_to",
				fieldtype: "Link",
				label: __("Assign To"),
				options: "User",
			},
			{
				fieldname: "due_date",
				fieldtype: "Date",
				label: __("Due Date"),
				default: frappe.datetime.add_days(frappe.datetime.get_today(), 3),
			},
			{
				fieldname: "description",
				fieldtype: "Small Text",
				label: __("Description"),
			},
		],
		primary_action_label: __("Create"),
		primary_action(values) {
			frappe
				.call({
					method: "frappe.client.insert",
					args: {
						doc: {
							doctype: "Accounting Request",
							subject: values.subject,
							request_type: values.request_type,
							due_date: values.due_date,
							description: values.description,
							reference_doctype: frm.doctype,
							reference_name: frm.docname,
							company: frm.doc.company,
							status: values.assign_to ? "Awaiting Response" : "Open",
						},
					},
				})
				.then((response) => {
					const request = response.message;
					if (values.assign_to) {
						return frappe
							.call({
								method: "frappe.desk.form.assign_to.add",
								args: {
									doctype: "Accounting Request",
									name: request.name,
									assign_to: [values.assign_to],
									description: values.subject,
									date: values.due_date,
								},
							})
							.then(() => request);
					}
					return request;
				})
				.then((request) => {
					dialog.hide();
					frappe.show_alert({
						message: __("Accounting Request {0} created", [
							`<a href="/app/accounting-request/${request.name}">${request.name}</a>`,
						]),
						indicator: "green",
					});
					frm.reload_doc();
				});
		},
	});

	dialog.show();
};

etransactions.accounting_hub.add_request_buttons = function (frm) {
	if (frm.is_new()) {
		return;
	}

	frm.add_custom_button(
		__("Request justificative"),
		() => etransactions.accounting_hub.make_accounting_request(frm, "Missing Justificative"),
		__("Accounting Hub")
	);
	frm.add_custom_button(
		__("Ask a question"),
		() => etransactions.accounting_hub.make_accounting_request(frm, "Question"),
		__("Accounting Hub")
	);
};
