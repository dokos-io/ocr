
from erpnext.setup.utils import identity as _


transactions_fields = [
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
		"fetch_from": "pending_purchase_invoice.file",
		"no_copy": 1
	},
	{
		"fieldname": "pending_purchase_invoice",
		"fieldtype": "Link",
		"options": "Pending Purchase Invoice",
		"label": _("Pending Purchase Invoice"),
		"insert_after": "ocr_original_file",
		"read_only": 1,
		"no_copy": 1
	},
]

TRANSACTION_FIELDS: dict = {
	"Purchase Order": transactions_fields,
	"Purchase Invoice": transactions_fields,
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
			"fieldname": "pending_purchase_invoice_item",
			"fieldtype": "Link",
			"options": "Pending Purchase Invoice Item",
			"label": _("Pending Purchase Invoice Item"),
			"insert_after": "ocr_request_line_item",
			"read_only": 1,
			"no_copy": 1
		},
	]
}