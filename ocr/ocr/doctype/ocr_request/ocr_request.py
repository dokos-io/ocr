# Copyright (c) 2023, Dokos SAS and contributors
# For license information, please see license.txt

import time

import frappe
from frappe.utils import time_diff_in_minutes, now_datetime, time_diff
from frappe.model.document import Document

from ocr.ocr.doctype.ocr_request.aws_textract import AWSTextract

class OCRRequest(Document):
	def after_insert(self):
		frappe.enqueue_doc(
			self.doctype,
			self.name,
			"make_analysis",
			queue="long",
			now=frappe.flags.in_test,
		)

	def make_analysis(self):
		self.start_analysis()
		self.get_analysis()

	def start_analysis(self):
		textract = AWSTextract(self)
		jobid = textract.start_analysis()
		self.db_set("job", jobid)

	def get_analysis(self):
		if self.analysis and frappe.parse_json(self.analysis).get("JobStatus") == "SUCCEEDED":
			return frappe.parse_json(self.analysis)

		textract = AWSTextract(self)
		if analysis := textract.get_analysis():
			if analysis["JobStatus"] == "SUCCEEDED":
				self.db_set("analysis", frappe.as_json(analysis))
				self.db_set("status", "Analysis Completed")

			elif time_diff_in_minutes(now_datetime(), self.creation) < 60:
				time.sleep(25)
				frappe.enqueue_doc(
					self.doctype,
					self.name,
					"get_analysis",
					queue="short"
				)

			elif time_diff(now_datetime(), self.creation) > 7:
				self.db_set("status", "Error")

		elif self.status != "Error":
			self.db_set("status", "Error")

		return analysis

	def on_trash(self):
		textract = AWSTextract(self)
		textract.delete_file()

	@frappe.whitelist()
	def create_purchase_invoice(self):
		purchase_invoice = frappe.new_doc("Purchase Invoice")

		analysis = self.get_analysis()
		parsed_data = analysis.get("ParsedDokosData")

		for d in parsed_data:
			if d == "items":
				for item in parsed_data[d]:
					purchase_invoice.append("items", item)
			else:
				purchase_invoice.set(d, parsed_data[d])

		purchase_invoice.ocr_request = self.name
		purchase_invoice.flags.ignore_mandatory = True
		purchase_invoice.flags.ignore_validate = True

		try:
			purchase_invoice.insert()
			self.db_set("status", "Transaction Created")
		except Exception as e:
			self.db_set("status", "Error")
			self.db_set("error", e)

def check_pending_analysis():
	for req in frappe.get_all("OCR Request", filters={"status": "Pending"}):
		doc = frappe.get_doc("OCR Request", req.name)
		doc.run_method("get_analysis")

@frappe.whitelist()
def get_analysis(request_id):
	doc = frappe.get_doc("OCR Request", request_id)
	return doc.get_analysis()

@frappe.whitelist()
def register_supplier_mapping(validated_data, service="AWS Textract"):
	data = frappe.parse_json(validated_data)

	for d in data:
		if d not in ["supplier", "items"]:
			continue

		if d == "supplier":
			if data.get("vendor_name") == data[d]:
				continue

			if existing_mapping := frappe.db.get_value("OCR Mapping",
				dict(
					ocr_service=service,
					key="VENDOR_NAME",
					value=data.get("vendor_name"),
					reference_doctype="Supplier"
				),
				["reference_name", "name"],
				as_dict=True
			):
				if existing_mapping.reference_name != data[d]:
					frappe.db.set_value("OCR Mapping", existing_mapping.name, "reference_name", data[d])


		if d == "items":
			for it in data[d]:
				if not frappe.db.get_value(
					"Item Supplier",
					dict(
						supplier=data["supplier"],
						supplier_part_no=it.get("item_name")
					),
				):
					item = frappe.get_doc("Item", it.get("item_code"))
					item.append("supplier_items", {
						"supplier": data["supplier"],
						"supplier_part_no": it.get("item_name")
					})
					item.flags.ignore_permissions = True
					item.save()