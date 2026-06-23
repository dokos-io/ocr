
from erpnext.setup.utils import identity as _


purchasing_fields = [
	{
		"fieldname": "ocr_tab",
		"fieldtype": "Tab Break",
		"label": _("Original Invoice"),
		"depends_on": "eval:doc.ocr_original_file",
		"insert_after": "connections_tab"
	},
	{
		"fieldname": "ocr_html",
		"fieldtype": "HTML",
		"label": _("Drop a file"),
		"insert_after": "ocr_tab",
	},
	{
		"fieldname": "ocr_request",
		"fieldtype": "Link",
		"options": "OCR Request",
		"label": _("OCR Request"),
		"insert_after": "ocr_html",
		"read_only": 1,
		"no_copy": 1
	},
	{
		"fieldname": "ocr_original_file",
		"fieldtype": "Link",
		"options": "File",
		"label": _("Original File"),
		"insert_after": "ocr_request",
		"read_only": 1,
		"fetch_from": "supplier_invoice.file",
		"no_copy": 1
	},
	{
		"fieldname": "supplier_invoice",
		"fieldtype": "Link",
		"options": "Supplier Invoice",
		"label": _("Supplier Invoice"),
		"insert_after": "ocr_original_file",
		"read_only": 1,
		"no_copy": 1
	},
]

# Shared reference field definitions. Placed in the Details area on orders, and moved
# into the eInvoice tab on Sales Invoice (see selling_fields vs sales_invoicing_fields).
buyer_reference_field = {
	"fieldname": "etransactions_buyer_reference",
	"label": _("Buyer Reference"),
	"fieldtype": "Data",
	"fetch_from": "customer.etransactions_buyer_reference",
	"fetch_if_empty": 1,
}

contract_reference_field = {
	"fieldname": "etransactions_contract_reference",
	"label": _("Contract Reference"),
	"description": _("Public-procurement contract number (numéro de marché, BT-12). Used for B2G / Chorus Pro."),
	"fieldtype": "Data",
	"fetch_from": "customer.etransactions_contract_reference",
	"fetch_if_empty": 1,
}

# Orders: references stay in the Details area after tax_id.
selling_fields = [
	{**buyer_reference_field, "insert_after": "tax_id"},
	{**contract_reference_field, "insert_after": "etransactions_buyer_reference"},
]

sales_invoicing_fields = [
	{
		"fieldname": "etransactions_tab",
		"fieldtype": "Tab Break",
		"label": _("eInvoice"),
		"insert_after": "terms",
	},
	{
		"fieldname": "etransaction_profile",
		"label": "eTransaction Profile",
		"fieldtype": "Link",
		"options": "eTransaction Profile",
		"insert_after": "etransactions_tab",
		"fetch_from": "customer.etransaction_profile",
		"fetch_if_empty": 1,
	},
	{**buyer_reference_field, "insert_after": "etransaction_profile"},
	{**contract_reference_field, "insert_after": "etransactions_buyer_reference"},
	{
		"fieldname": "etransactions_status_html",
		"fieldtype": "HTML",
		"label": "",
		"insert_after": "etransactions_contract_reference",
	},
]

purchase_invoicing_fields = [
	{
		"fieldname": "etransactions_tab",
		"fieldtype": "Tab Break",
		"label": _("eInvoice"),
		"insert_after": "terms",
	},
	{
		"fieldname": "etransactions_status_html",
		"fieldtype": "HTML",
		"label": "",
		"insert_after": "etransactions_tab",
	},
]

TRANSACTION_FIELDS: dict = {
	"Purchase Order": purchasing_fields,
	"Purchase Invoice": purchasing_fields + purchase_invoicing_fields,
	"Purchase Order Item": [
		{
			"fieldname": "ocr_request_line_item",
			"fieldtype": "Link",
			"options": "OCR Line Items Mapping",
			"label": _("OCR Request Line Item"),
			"insert_after": "supplier_quotation_item",
			"read_only": 1,
			"no_copy": 1
		},
		{
			"fieldname": "supplier_invoice_item",
			"fieldtype": "Link",
			"options": "Supplier Invoice Item",
			"label": _("Supplier Invoice Item"),
			"insert_after": "ocr_request_line_item",
			"read_only": 1,
			"no_copy": 1
		},
	],
	"Sales Order": selling_fields,
	"Sales Invoice": sales_invoicing_fields,
}