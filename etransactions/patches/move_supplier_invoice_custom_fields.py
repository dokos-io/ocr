from etransactions.etransactions.doctype.supplier_invoice.custom_fields import move_existing_custom_fields


def execute():
	"""Show the custom fields of supplier invoices on their Review tab."""
	move_existing_custom_fields()
