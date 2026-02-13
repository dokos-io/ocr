from erpnext.setup.utils import identity as _


customer_fields = [
	{
		"fieldname": "etransactions_tab",
		"fieldtype": "Tab Break",
		"label": _("eTransactions"),
		"insert_after": "selling_party_html"
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

MASTER_DATA_FIELDS = {
	"Customer": customer_fields,
	"Company": company_fields
}