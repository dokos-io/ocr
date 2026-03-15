// Copyright (c) 2025, Dokos SAS and Contributors
// License: See license.txt
frappe.provide("frappe.ui.document_timeline_settings");

frappe.ui.document_timeline_settings["Supplier Invoice"] = [
	{
		doctype: "Supplier Invoices Basket",
		fields: ["status"],
		timeline_date: "creation",
		link_field: "ocr_basket",
	},
	{
		doctype: "OCR Request",
		fields: ["status"],
		timeline_date: "creation",
		link_field: "ocr_request",
	},
	{
		doctype: "Supplier Invoice",
		fields: ["status"],
		timeline_date: "bill_date",
		timeline_amount: "grand_total",
	},
	{
		doctype: "Purchase Order",
		fields: ["workflow_state", "status"],
		timeline_date: "transaction_date",
		link_field: "reference_docname",
		link_field_doctype: "Supplier Invoice Item",
		timeline_amount: "grand_total",
	},
	{
		doctype: "Purchase Receipt",
		fields: ["status"],
		timeline_date: "posting_date",
		link_field: "reference_docname",
		link_field_doctype: "Supplier Invoice Item",
		timeline_amount: "net_total",
	},
	{
		doctype: "Purchase Invoice",
		fields: ["workflow_state", "status"],
		timeline_date: "posting_date",
		link_field: "supplier_invoice",
		timeline_amount: "grand_total",
	},
];
