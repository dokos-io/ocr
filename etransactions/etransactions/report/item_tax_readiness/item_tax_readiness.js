// Copyright (c) 2026, Dokos SAS and Contributors
// License: GNU General Public License v3. See license.txt

frappe.query_reports["Item Tax Readiness"] = {
	filters: [
		{
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
		{
			fieldname: "only_without_taxes",
			label: __("Only Show Items with Issues"),
			fieldtype: "Check",
			default: 1,
		},
	],

	formatter: function (value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);

		if (!data) return value;

		if (column.fieldname === "issues" && data.issues) {
			return `<span style="color: var(--red-600, #e53e3e);">${value}</span>`;
		}

		if (column.fieldname === "missing_coverage" && data.missing_coverage) {
			return `<span style="color: var(--red-600, #e53e3e);">${value}</span>`;
		}

		if (column.fieldname === "tax_templates" && !data.tax_templates) {
			return `<span style="color: var(--red-600, #e53e3e);">—</span>`;
		}

		return value;
	},
};
