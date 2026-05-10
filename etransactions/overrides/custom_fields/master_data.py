from erpnext.setup.utils import identity as _


customer_fields = [
	{
		"fieldname": "siren_number",
		"label": _("SIREN Number"),
		"fieldtype": "Data",
		"insert_after": "tax_id",
		"length": 9,
	},
	{
		"fieldname": "etransactions_tab",
		"fieldtype": "Tab Break",
		"label": _("eTransactions"),
		"insert_after": "selling_party_html",
	},
	{
		"fieldname": "etransaction_profile",
		"label": "eTransaction Profile",
		"fieldtype": "Link",
		"options": "eTransaction Profile",
		"insert_after": "etransactions_tab",
	},
	{
		"fieldname": "etransactions_buyer_reference",
		"label": _("Buyer Reference"),
		"insert_after": "etransaction_profile",
		"fieldtype": "Data",
	},
	{
		"fieldname": "etransactions_electronic_address_scheme",
		"label": _("Electronic Address Scheme"),
		"insert_after": "etransactions_buyer_reference",
		"fieldtype": "Link",
		"options": "Common Code",
	},
	{
		"fieldname": "etransactions_electronic_address",
		"label": _("Electronic Address"),
		"insert_after": "etransactions_electronic_address_scheme",
		"fieldtype": "Data",
		"depends_on": "etransactions_electronic_address_scheme",
	},
	# Accredited platform directory fields
	{
		"fieldname": "pa_directory_section",
		"label": _("Accredited Platform Directory"),
		"fieldtype": "Section Break",
		"insert_after": "etransactions_electronic_address",
		"collapsible": 1,
	},
	{
		"fieldname": "directory_entity_type",
		"label": _("Directory Entity Type"),
		"fieldtype": "Select",
		"options": "\nprivate\npublic\nno",
		"insert_after": "pa_directory_section",
		"read_only": 1,
		"in_list_view": 0,
	},
	{
		"fieldname": "directory_name",
		"label": _("Name in Directory"),
		"fieldtype": "Data",
		"insert_after": "directory_entity_type",
		"read_only": 1,
	},
	{
		"fieldname": "directory_closed",
		"label": _("Entity Closed in Directory"),
		"fieldtype": "Check",
		"insert_after": "directory_name",
		"read_only": 1,
	},
	{
		"fieldname": "pa_directory_col_break",
		"fieldtype": "Column Break",
		"insert_after": "directory_closed",
	},
	{
		"fieldname": "directory_update_date",
		"label": _("Directory Last Updated"),
		"fieldtype": "Date",
		"insert_after": "pa_directory_col_break",
		"read_only": 1,
	},
	{
		"fieldname": "directory_siren",
		"label": _("SIREN (last query)"),
		"fieldtype": "Data",
		"insert_after": "directory_update_date",
		"read_only": 1,
	},
	{
		"fieldname": "default_directory_line",
		"label": _("Default Directory Line"),
		"fieldtype": "Link",
		"options": "eInvoicing Directory Line",
		"insert_after": "directory_siren",
		"description": _("Default routing line used when creating invoices for this customer"),
	},
	{
		"fieldname": "accredited_platform_override",
		"label": _("eTransactions Accredited Platform Override"),
		"fieldtype": "Link",
		"options": "eTransactions Accredited Platform",
		"insert_after": "default_directory_line",
		"description": _("Override the default eTransactions Accredited Platform for this customer"),
	},
]

company_fields = [
		{
			"fieldname": "etransactions_tab",
			"fieldtype": "Tab Break",
			"label": _("eTransactions"),
			"insert_after": "connections_tab"
		},
		{
			"fieldname": "etransactions_seller_reference",
			"label": _("Seller Reference"),
			"insert_after": "etransactions_tab",
			"fieldtype": "Data",
		},
		{
			"fieldname": "etransactions_electronic_address_scheme",
			"label": _("Electronic Address Scheme"),
			"insert_after": "etransactions_seller_reference",
			"fieldtype": "Link",
			"options": "Common Code",
		},
		{
			"fieldname": "etransactions_electronic_address",
			"label": _("Electronic Address"),
			"insert_after": "etransactions_electronic_address_scheme",
			"fieldtype": "Data",
			"depends_on": "etransactions_electronic_address_scheme",
		},
]

customer_group_fields = [
	{
		"fieldname": "accredited_platform_override",
		"label": _("eTransactions Accredited Platform Override"),
		"fieldtype": "Link",
		"options": "eTransactions Accredited Platform",
		"insert_after": "parent_customer_group",
		"description": _("Override the default eTransactions Accredited Platform for customers in this group"),
	},
]

MASTER_DATA_FIELDS = {
	"Customer": customer_fields,
	"Company": company_fields,
	"Customer Group": customer_group_fields
}