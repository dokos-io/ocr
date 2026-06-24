
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

# The accredited-platform routing line (establishment) the e-invoice is sent to.
# Resolved automatically from the buyer's directory; editable to force a specific
# establishment. Shared by Sales Order (where it is determined at confirmation)
# and Sales Invoice (where it is propagated and drives the eInvoice routing).
routing_line_field = {
	"fieldname": "etransactions_routing_line",
	"label": _("Accredited-Platform Routing Line"),
	"fieldtype": "Link",
	"options": "eInvoicing Directory Line",
	"description": _("Directory line used to route the e-invoice. Resolved automatically; override to force a specific establishment."),
}

# Orders: references stay in the Details area after tax_id.
selling_fields = [
	{**buyer_reference_field, "insert_after": "tax_id"},
	{**contract_reference_field, "insert_after": "etransactions_buyer_reference"},
	{**routing_line_field, "insert_after": "etransactions_contract_reference"},
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
	# The regulated-flow determination (single source of truth), set on validate by
	# classify_transaction so the user sees why an invoice is sent or e-reported.
	{
		"fieldname": "etransactions_flow_class",
		"label": _("Regulated Flow"),
		"fieldtype": "Select",
		"options": "\nB2B\nB2G\nB2C\nB2Bi\nOutOfScope",
		"insert_after": "etransactions_contract_reference",
		"read_only": 1,
		"no_copy": 1,
		"description": _("How this invoice is handled under the French CTC reform: B2B/B2G are e-invoiced, B2C/B2Bi are e-reported."),
	},
	{**routing_line_field, "insert_after": "etransactions_flow_class"},
	{
		"fieldname": "etransactions_status_html",
		"fieldtype": "HTML",
		"label": "",
		"insert_after": "etransactions_routing_line",
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