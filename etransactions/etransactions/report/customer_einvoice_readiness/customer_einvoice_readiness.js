// Copyright (c) 2026, Dokos SAS and Contributors
// License: GNU General Public License v3. See license.txt

frappe.query_reports["Customer eInvoice Readiness"] = {
	filters: [
		{
			fieldname: "customer_group",
			label: __("Customer Group"),
			fieldtype: "Link",
			options: "Customer Group",
		},
		{
			fieldname: "only_with_issues",
			label: __("Only Show Customers with Issues"),
			fieldtype: "Check",
			default: 1,
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (!data) return value;

		// Highlight the Issues column in red when there are issues
		if (column.fieldname === "issues" && data.issues) {
			return `<span style="color: var(--red-600, #e53e3e);">${value}</span>`;
		}

		// Flag missing mandatory fields in red
		const mandatory_fields = [
			"siren_number",
			"tax_id",
			"billing_address",
			"siret_number",
			"address_line1",
			"city",
			"pincode",
			"country",
		];
		if (mandatory_fields.includes(column.fieldname) && !data[column.fieldname]) {
			return `<span style="color: var(--red-600, #e53e3e);">—</span>`;
		}

		// Flag missing email in amber (not mandatory, but informational)
		if (column.fieldname === "email_id" && !data.email_id) {
			return `<span style="color: var(--yellow-600, #d97706);" title="${__(
				"Will be auto-filled from primary contact once the dedicated field is available"
			)}">—</span>`;
		}

		return value;
	},
};
