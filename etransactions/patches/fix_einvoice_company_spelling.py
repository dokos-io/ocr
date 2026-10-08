import frappe

from etransactions.controllers.entity_resolver import canonical_company, resolve_buyer_company

DOCTYPES = ("eInvoice", "Supplier Invoice")


def execute():
	"""Put the company of received invoices back to a Company's stored name.

	eInvoice.guess_company() used to store the buyer name as printed on the invoice
	whenever the database found a Company that matched it case- and accent-insensitively:
	"MIROITERIE AVIGNONNAISE" instead of "Miroiterie Avignonnaise". User permissions
	compare the stored value exactly, so those invoices were refused to users restricted
	to that company. The Supplier Invoices built from them copied the same value.

	Incoming eInvoices left without a company are matched again, by SIREN, VAT number or
	name, but never given the default company: that guess is what left them empty.
	"""
	companies = set(frappe.get_all("Company", pluck="name"))

	for doctype in DOCTYPES:
		if not frappe.db.table_exists(doctype):
			continue
		# Deduplicate in Python: a database DISTINCT folds "miroiterie avignonnaise" into
		# "Miroiterie Avignonnaise" and returns one of them, which hid every variant of a
		# Company whose stored spelling was also present.
		for value in set(frappe.get_all(doctype, filters={"company": ("is", "set")}, pluck="company")):
			if value in companies:
				continue
			if company := canonical_company(value):
				_replace_company(doctype, value, company)

	if frappe.db.table_exists("eInvoice"):
		_match_incoming_without_company()


def _replace_company(doctype: str, value: str, company: str) -> None:
	# frappe.get_all filters compare case-insensitively too: select by exact bytes.
	names = [
		row.name
		for row in frappe.get_all(doctype, filters={"company": value}, fields=["name", "company"])
		if row.company == value
	]
	for name in names:
		frappe.db.set_value(doctype, name, "company", company, update_modified=False)
	if names:
		print(f"{doctype}: company '{value}' -> '{company}' on {len(names)} document(s)")


def _match_incoming_without_company() -> None:
	einvoices = frappe.get_all(
		"eInvoice",
		filters={"einvoice_type": "Incoming", "company": ("in", ("", None))},
		fields=[
			"name",
			"buyer_name",
			"buyer_tax_id",
			"buyer_electronic_address",
			"buyer_electronic_address_scheme",
		],
	)
	for einvoice in einvoices:
		company = resolve_buyer_company(
			einvoice.buyer_name,
			tax_id=einvoice.buyer_tax_id,
			electronic_address=einvoice.buyer_electronic_address,
			electronic_address_scheme=einvoice.buyer_electronic_address_scheme,
			use_default=False,
		)
		if not company:
			continue

		frappe.db.set_value("eInvoice", einvoice.name, "company", company, update_modified=False)
		frappe.db.set_value(
			"Supplier Invoice",
			{"einvoice": einvoice.name, "company": ("in", ("", None))},
			"company",
			company,
			update_modified=False,
		)
		print(f"eInvoice {einvoice.name}: company set to '{company}'")
