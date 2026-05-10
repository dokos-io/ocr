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
		"title", "vendor_address", "tax_id", "is_return", "original_invoice",
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
]


def add_custom_fields():
	click.secho("* Updating eTransactions Custom Fields")
	_delete_ocr_custom_fields()

	custom_fields = get_custom_fields()
	create_custom_fields(custom_fields, ignore_validate=frappe.flags.in_patch, update=True)

	for dt in custom_fields:
		frappe.clear_cache(doctype=dt)


def _delete_ocr_custom_fields():
	for field in CUSTOM_FIELDS_TO_DELETE:
		if frappe.db.exists("Custom Field", {"dt": field["dt"], "fieldname": field["fieldname"]}):
			frappe.delete_doc("Custom Field", f"{field['dt']}-{field['fieldname']}", ignore_missing=True)
			frappe.clear_cache(doctype=field["dt"])


def get_custom_fields():
	from etransactions.overrides.custom_fields import CUSTOM_FIELDS
	return CUSTOM_FIELDS
