import frappe

# Fields the Factur-X parser filled with the text "None" when the invoice left them empty.
FIELDS = (
	"seller_country",
	"buyer_country",
	"seller_electronic_address",
	"seller_electronic_address_scheme",
	"buyer_electronic_address",
	"buyer_electronic_address_scheme",
)


def execute():
	"""Clear the text "None" left by the parser. A country of "None" fails link validation,
	so the eInvoice can no longer be saved."""
	for field in FIELDS:
		frappe.db.set_value("eInvoice", {field: "None"}, field, None, update_modified=False)
