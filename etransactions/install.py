import click

import frappe
from frappe.query_builder import DocType
from pypika.terms import ValueWrapper

from frappe.installer import remove_app
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import now_datetime
from frappe.model.sync import sync_for



def after_install():
	sync_for("etransactions", force=True, reset_permissions=True)
	add_custom_fields()
	rename_ocr_to_etransactions()
	frappe.delete_doc("Workspace", "Data Extraction", ignore_missing=True, force=True)
	import_peppol_participant_identifier_schemes()


def import_peppol_participant_identifier_schemes():
	import os
	from erpnext.edi.doctype.code_list.code_list_import import import_genericode_content, process_genericode_import

	file_path = frappe.get_app_path("etransactions", "data", "peppol_participant_identifier_schemes.xml")
	if not os.path.exists(file_path):
		return

	with open(file_path, "rb") as f:
		content = f.read()

	frappe.set_user("Administrator")

	from erpnext.edi.doctype.code_list.code_list import CodeList

	if not hasattr(CodeList, "from_peppol"):
		# the upstream ERPNext only reads genericode files
		import_peppol_schemes_without_erpnext_support(content)
		return

	result = import_genericode_content(
		doctype="Code List",
		docname=None,
		content=content,
		file_name="peppol_participant_identifier_schemes.xml"
	)

	code_list_name = result["code_list"]
	file_doc_name = result["file"]

	if frappe.db.exists("Common Code", {"code_list": code_list_name}):
		return

	process_genericode_import(
		code_list_name=code_list_name,
		file_name=file_doc_name,
		code_column="iso6523",
		title_column="scheme-name",
		description_column="usage",
		filters=None
	)


def import_peppol_schemes_without_erpnext_support(content: bytes):
	"""Create the Code List and Common Codes the Dokos ERPNext importer creates."""
	from lxml import etree

	root = etree.fromstring(content, parser=etree.XMLParser(remove_blank_text=True, resolve_entities=False))
	version = root.get("version")
	code_list_name = f"Peppol Participant Identifier Schemes v{version}"

	if not frappe.db.exists("Code List", code_list_name):
		code_list = frappe.new_doc("Code List")
		code_list.name = code_list_name
		code_list.title = code_list_name
		code_list.version = version
		code_list.canonical_uri = f"https://peppol.eu/code-lists/participant-identifier-schemes/{version}"
		code_list.publisher = "OpenPeppol"
		code_list.url = "https://docs.peppol.eu/edelivery/codelists/"
		code_list.insert()

	if frappe.db.exists("Common Code", {"code_list": code_list_name}):
		return

	def get_value(element, name):
		return element.get(name) or getattr(element.find(f"./{name}"), "text", None)

	for element in root.findall(".//participant-identifier-scheme"):
		code = get_value(element, "iso6523")
		common_code = frappe.new_doc("Common Code")
		common_code.code_list = code_list_name
		common_code.common_code = code
		common_code.title = get_value(element, "scheme-name") or code
		common_code.description = get_value(element, "usage")
		common_code.additional_data = etree.tostring(element, encoding="unicode", pretty_print=True)
		common_code.insert()


def rename_ocr_to_etransactions():
	"""
	Migrate data from OCR app doctypes to eTransactions app doctypes.
	"""
	if not frappe.db.exists("Module Def", "OCR"):
		return

	_migrate_settings()
	_migrate_baskets()
	_migrate_supplier_invoices()
	_migrate_supplier_invoice_items()
	_migrate_purchasing_document_links()
	_migrate_file_links()
	_migrate_references()

	# remove_app(app_name="ocr", dry_run=False, yes=True, no_backup=True)


def _read_ocr_settings():
	"""Return current eTransactions Settings values stored by the OCR app."""
	settings = frappe.get_single("OCR Settings")
	aws_textract_secret = None
	if settings.get("aws_textract_secret"):
		aws_textract_secret = settings.get_password("aws_textract_secret")
	settings_dict = settings.as_dict()
	settings_dict["aws_textract_secret"] = aws_textract_secret
	return settings_dict


def _migrate_settings():
	"""Restore eTransactions Settings values after OCR app removal."""
	ocr_settings = _read_ocr_settings()

	if not ocr_settings:
		return

	valid_fields = {f.fieldname for f in frappe.get_meta("eTransactions Settings").fields}
	for fieldname, value in ocr_settings.items():
		if fieldname in valid_fields and value is not None:
			frappe.db.set_single_value("eTransactions Settings", fieldname, value)


def _migrate_file_links():
	"""Update tabFile.attached_to_doctype for all renamed doctypes"""
	File = DocType("File")
	doctype_renames = [
		("OCR Purchase Invoice Basket", "Supplier Invoices Basket"),
		("Pending Purchase Invoice", "Supplier Invoice"),
		("Pending Purchase Invoice Item", "Supplier Invoice Item"),
	]
	for old_name, new_name in doctype_renames:
		(
			frappe.qb.update(File)
			.set(File.attached_to_doctype, new_name)
			.where(File.attached_to_doctype == old_name)
			.run()
		)


OCR_DOCTYPE_RENAMES = {
	"OCR Purchase Invoice Basket": "Supplier Invoices Basket",
	"Pending Purchase Invoice": "Supplier Invoice",
}

# Documents that point to a record by DocType name: they keep working once re-pointed
# because the records keep their names.
REFERENCE_FIELDS = (
	("ToDo", "reference_type"),
	("DocShare", "share_doctype"),
	("Comment", "reference_doctype"),
	("Version", "ref_doctype"),
	("Communication", "reference_doctype"),
	("Communication Link", "link_doctype"),
	("Notification Log", "document_type"),
	("Document Follow", "ref_doctype"),
	("Email Account", "append_to"),
	("Assignment Rule", "document_type"),
	("Notification", "document_type"),
	("Number Card", "document_type"),
	("Dashboard Chart", "document_type"),
)


def _migrate_references():
	"""Point assignments, timeline, mail intake and dashboards at the renamed DocTypes."""
	for doctype, fieldname in REFERENCE_FIELDS:
		if not frappe.db.has_column(doctype, fieldname):
			continue

		table = DocType(doctype)
		for old_name, new_name in OCR_DOCTYPE_RENAMES.items():
			(
				frappe.qb.update(table)
				.set(table[fieldname], new_name)
				.where(table[fieldname] == old_name)
				.run()
			)


def _migrate_baskets():
	"""Copy OCR Purchase Invoice Basket → Supplier Invoices Basket"""
	if not frappe.db.table_exists("OCR Purchase Invoice Basket"):
		return

	columns = [
		"name", "creation", "modified", "modified_by", "owner", "docstatus", "idx",
		"title", "sender", "subject", "status", "error",
		"_user_tags", "_comments", "_assign", "_liked_by",
	]
	old = DocType("OCR Purchase Invoice Basket")
	new = DocType("Supplier Invoices Basket")

	(
		frappe.qb.into(new)
		.columns(*[new[c] for c in columns])
		.from_(old)
		.select(*[old[c] for c in columns])
		.where(old.name.notin(frappe.qb.from_(new).select(new.name)))
		.run()
	)


def _migrate_supplier_invoices():
	"""Copy Pending Purchase Invoice → Supplier Invoice"""
	if not frappe.db.table_exists("Pending Purchase Invoice"):
		return

	columns = [
		"name", "creation", "modified", "modified_by", "owner", "docstatus", "idx",
		"status", "supplier", "supplier_name", "bill_no", "bill_date", "posting_date",
		"due_date", "company", "currency",
		"supplier_net_amount", "supplier_tax_amount", "supplier_grand_total",
		"net_total", "tax_total", "grand_total",
		"tax_category", "taxes_and_charges",
		"file", "file_url", "ocr_request", "ocr_basket",
		"title", "vendor_address", "tax_id", "is_return",
		"_user_tags", "_comments", "_assign", "_liked_by",
	]
	old = DocType("Pending Purchase Invoice")
	new = DocType("Supplier Invoice")

	(
		frappe.qb.into(new)
		.columns(*[new[c] for c in columns])
		.from_(old)
		.select(*[old[c] for c in columns])
		.where(old.name.notin(frappe.qb.from_(new).select(new.name)))
		.run()
	)


def _migrate_supplier_invoice_items():
	"""Copy Pending Purchase Invoice Item → Supplier Invoice Item"""
	if not frappe.db.table_exists("Pending Purchase Invoice Item"):
		return

	columns = [
		"name", "creation", "modified", "modified_by", "owner", "docstatus", "idx",
		"parent", "parentfield",
		"supplier_description", "supplier_item_code", "item_code",
		"qty", "rate", "amount", "description",
		"cost_center", "project", "expense_account", "item_tax_template",
		"reference_doctype", "reference_docname", "row",
	]
	old = DocType("Pending Purchase Invoice Item")
	new = DocType("Supplier Invoice Item")

	(
		frappe.qb.into(new)
		.columns(*[new[c] for c in columns], new.parenttype)
		.from_(old)
		.select(*[old[c] for c in columns], ValueWrapper("Supplier Invoice"))
		.where(
			(old.parenttype == "Pending Purchase Invoice")
			& old.name.notin(frappe.qb.from_(new).select(new.name))
		)
		.run()
	)


def _migrate_purchasing_document_links():
	"""
	Copy linked field values from the old OCR custom fields to the new eTransactions ones.

	OCR added: pending_purchase_invoice / pending_purchase_invoice_item
	eTransactions adds: supplier_invoice / supplier_invoice_item
	Both columns exist on the tables while both apps are installed.
	"""
	if frappe.db.has_column("Purchase Order", "pending_purchase_invoice"):
		po = DocType("Purchase Order")
		(
			frappe.qb.update(po)
			.set(po.supplier_invoice, po.pending_purchase_invoice)
			.where(
				po.pending_purchase_invoice.isnotnull()
				& (po.pending_purchase_invoice != "")
			)
			.run()
		)

	if frappe.db.has_column("Purchase Order Item", "pending_purchase_invoice_item"):
		poi = DocType("Purchase Order Item")
		(
			frappe.qb.update(poi)
			.set(poi.supplier_invoice_item, poi.pending_purchase_invoice_item)
			.where(
				poi.pending_purchase_invoice_item.isnotnull()
				& (poi.pending_purchase_invoice_item != "")
			)
			.run()
		)

	if frappe.db.has_column("Purchase Invoice", "pending_purchase_invoice"):
		pi = DocType("Purchase Invoice")
		(
			frappe.qb.update(pi)
			.set(pi.supplier_invoice, pi.pending_purchase_invoice)
			.where(
				pi.pending_purchase_invoice.isnotnull()
				& (pi.pending_purchase_invoice != "")
			)
			.run()
		)





CUSTOM_FIELDS_TO_DELETE = [
	{
		"dt": "Purchase Order",
		"fieldname": "pending_purchase_invoice",
		"fieldtype": "Link",
		"options": "Pending Purchase Invoice",
	},
	{
		"dt": "Purchase Invoice",
		"fieldname": "pending_purchase_invoice",
		"fieldtype": "Link",
		"options": "Pending Purchase Invoice",
	},
	{
		"dt": "Purchase Order Item",
		"fieldname": "pending_purchase_invoice_item",
		"fieldtype": "Link",
		"options": "Pending Purchase Invoice Item",
	},
	# Removed: never read by any code path.
	{
		"dt": "Company",
		"fieldname": "etransactions_seller_reference",
		"fieldtype": "Data",
	},
	# Removed: redundant with siren_number; routing now keyed on SIRET/Address.
	{
		"dt": "Customer",
		"fieldname": "directory_siren",
		"fieldtype": "Data",
	},
	# Removed: duplicated erpnext France's standard Address.siret_number, which
	# routing now matches on. See plateforme_agreee/routing.py::address_for_siret.
	{
		"dt": "Address",
		"fieldname": "siret",
		"fieldtype": "Data",
	},
	# Removed: replaced by the etransactions_tab Tab Break (was a Section Break
	# nested inside whatever tab siret_number happened to be in).
	{
		"dt": "Address",
		"fieldname": "etransactions_section",
		"fieldtype": "Section Break",
	},
	# Removed: the establishments table now lives inside the collapsible routing
	# section (pa_directory_section); its standalone section break is obsolete.
	{
		"dt": "Customer",
		"fieldname": "pa_establishments_section",
		"fieldtype": "Section Break",
	},
	# Removed: the B2G references are establishment-/document-specific, not a
	# per-customer default. The service code (BT-10) now lives on the Address and
	# the contract number (BT-12) is entered per invoice/order.
	{
		"dt": "Customer",
		"fieldname": "etransactions_buyer_reference",
		"fieldtype": "Data",
	},
	{
		"dt": "Customer",
		"fieldname": "etransactions_contract_reference",
		"fieldtype": "Data",
	},
	# Removed: Esalink partner credentials now live in site_config.json only (no
	# per-company override); the Esalink account is created per company at platform setup.
	*[
		{"dt": "Company", "fieldname": fieldname}
		for fieldname in (
			"etransactions_esalink_section",
			"etransactions_esalink_environment",
			"etransactions_esalink_api_key",
			"etransactions_esalink_partner_column",
			"etransactions_esalink_partner_username",
			"etransactions_esalink_partner_password",
		)
	],
	# Removed: a supplier is the seller on incoming invoices — its electronic
	# address (BT-34/BT-49) is never emitted by anything we generate. Only the
	# Company and Customer endpoints are used (see einvoice/generator.py), so the
	# supplier picker + save-time EAS guard were dead weight.
	{"dt": "Supplier", "fieldname": "etransactions_electronic_address_scheme", "fieldtype": "Link"},
	{"dt": "Supplier", "fieldname": "etransactions_electronic_address", "fieldtype": "Data"},
]


def add_custom_fields():
	click.secho("* Updating eTransactions Custom Fields")
	_delete_obsolete_custom_fields()

	custom_fields = _for_installed_erpnext(_with_explicit_hidden(get_custom_fields()))
	create_custom_fields(custom_fields, ignore_validate=frappe.flags.in_patch, update=True)

	for dt in custom_fields:
		frappe.clear_cache(doctype=dt)


def _with_explicit_hidden(custom_fields):
	"""Force an explicit ``hidden`` on every managed field.

	create_custom_fields(update=True) only overrides keys present in the definition,
	so a field whose definition omits ``hidden`` can keep a legacy stored hidden=1
	forever — that is why the eTransactions tabs stayed hidden on installed sites even
	when e-invoicing was enabled. Defaulting hidden to 0 here makes every install/migrate
	reconcile it; the two intentionally hidden fields keep their explicit hidden=1
	because ``df`` is spread last.
	"""
	return {
		dt: [{"hidden": 0, **df} for df in fields]
		for dt, fields in custom_fields.items()
	}


def _for_installed_erpnext(custom_fields):
	"""Adapt the managed fields to an ERPNext without the Dokos fields.

	Dokos ships Company.siren_number as a standard field: add it when it is missing.
	A field anchored on a field that does not exist goes after the last field of the form.
	"""
	custom_fields = {dt: list(fields) for dt, fields in custom_fields.items()}

	if not frappe.get_meta("Company").has_field("siren_number"):
		custom_fields.setdefault("Company", []).insert(
			0,
			{
				"fieldname": "siren_number",
				"label": "SIREN Number",
				"fieldtype": "Data",
				"insert_after": "tax_id",
				"length": 9,
			},
		)

	for doctypes, fields in custom_fields.items():
		for doctype in [doctypes] if isinstance(doctypes, str) else doctypes:
			meta = frappe.get_meta(doctype)
			fieldnames = {df["fieldname"] for df in fields}
			last_field = next(
				(df.fieldname for df in reversed(meta.fields) if df.fieldname not in fieldnames), None
			)
			for df in fields:
				anchor = df.get("insert_after")
				if anchor and not meta.has_field(anchor) and anchor not in fieldnames:
					df["insert_after"] = last_field

	return custom_fields


def _delete_obsolete_custom_fields():
	for field in CUSTOM_FIELDS_TO_DELETE:
		if frappe.db.exists("Custom Field", {"dt": field["dt"], "fieldname": field["fieldname"]}):
			frappe.delete_doc("Custom Field", f"{field['dt']}-{field['fieldname']}", ignore_missing=True)
			frappe.clear_cache(doctype=field["dt"])


def get_custom_fields():
	from etransactions.overrides.custom_fields import CUSTOM_FIELDS
	return CUSTOM_FIELDS
