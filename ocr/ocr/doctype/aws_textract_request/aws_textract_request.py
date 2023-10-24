# Copyright (c) 2023, Dokos SAS and contributors
# For license information, please see license.txt

import boto3
import io

from botocore.exceptions import ClientError

import frappe
from frappe.model.document import Document

class AWSTextractRequest(Document):
	def after_insert(self):
		textract = AWSTextract(self)
		jobid = textract.start_analysis()
		self.db_set("job", jobid)

	def get_analysis(self):
		textract = AWSTextract(self)
		analysis = textract.get_analysis()

		if analysis["JobStatus"] == "SUCCEEDED":
			self.db_set("status", "Completed")

		return analysis

@frappe.whitelist()
def new_request(file_doc, response):
	doc = frappe.parse_json(file_doc)
	request = frappe.new_doc("AWS Textract Request")
	request.filename = doc.get("file_name")
	request.file = doc.get("name")
	request.save()

	return request.name

@frappe.whitelist()
def get_analysis(request_id):
	doc = frappe.get_doc("AWS Textract Request", request_id)
	return doc.get_analysis()

class AWSTextract:
	def __init__(self, doc):
		self.textract_client = boto3.client(
			'textract',
			aws_access_key_id=frappe.conf.aws_textract_key,
			aws_secret_access_key=frappe.conf.aws_textract_secret,
			region_name="eu-west-3"
		)

		self.doc = doc

	def start_analysis(self):
		self.upload_doc_to_bucket()

		response = self.textract_client.start_expense_analysis(
			DocumentLocation={
				'S3Object': {
					'Bucket': self.bucket,
					'Name': self.doc.filename,
				}}
		)

		return response.get("JobId")

	def upload_doc_to_bucket(self):
		self.bucket = frappe.conf.ocr_s3_bucket or "dokos-ocr"

		self.s3_client = boto3.client(
			's3',
			aws_access_key_id=frappe.conf.aws_textract_key,
			aws_secret_access_key=frappe.conf.aws_textract_secret,
			region_name="eu-west-3"
		)

		self.create_bucket()
		self.upload_file()

	def create_bucket(self):
		try:
			self.s3_client.head_bucket(Bucket=self.bucket)
		except ClientError:
			self.s3_client.create_bucket(
				Bucket=self.bucket,
				CreateBucketConfiguration={
					'LocationConstraint': 'eu-west-3'
				},
			)

	def upload_file(self):
		file = frappe.get_doc("File", self.doc.file)
		self.s3_client.upload_fileobj(
			io.BytesIO(file.get_content()),
			self.bucket,
			self.doc.filename
		)

	def delete_file(self):
		self.s3_client.delete_object(
			Bucket=self.bucket,
			Key=self.doc.filename,
		)

	def get_analysis(self):
		analysis = self._get_analysis_from_textract()
		return self.parse_analysis(analysis)

	def _get_analysis_from_textract(self):
		return self.textract_client.get_expense_analysis(JobId=self.doc.job)

	def parse_analysis(self, analysis):
		result = frappe._dict(
			_children=[]
		)

		for expense in analysis.get("ExpenseDocuments") or []:
			for field in expense["SummaryFields"]:
				result[field["Type"].get("Text")] = field["ValueDetection"].get("Text")


			for line in expense["LineItemGroups"]:
				for item in line["LineItems"]:
					row = {}
					for field in item["LineItemExpenseFields"]:
						row[field["Type"].get("Text")] = field["ValueDetection"].get("Text")
					result._children.append(row)

		analysis["ParsedDokosData"] = self.get_purchase_invoice_data(result)
		return analysis

	def get_purchase_invoice_data(self, result):
		purchase_invoice = frappe._dict(items=[])
		purchase_invoice["supplier"] = self.get_supplier_name(result)
		purchase_invoice["bill_no"] = result.get("INVOICE_RECEIPT_ID")
		purchase_invoice["bill_date"] = result.get("INVOICE_RECEIPT_DATE")

		for child in result._children:
			purchase_invoice["items"].append(
				{
					"item_name": child["ITEM"],
					"qty": child["QUANTITY"],
					"rate": child["UNIT_PRICE"],
					"description": child["EXPENSE_ROW"]
				}
			)

		return purchase_invoice

	def get_supplier_name(self, result):
		print(result)
		supplier = None
		if result.get("VENDOR_VAT_NUMBER"):
			supplier = frappe.db.get_value("Supplier", dict(tax_id=result.get("VENDOR_VAT_NUMBER")))

		if not supplier and result.get("VENDOR_NAME"):
			supplier = frappe.db.get_value("Supplier", result.get("VENDOR_NAME"))

		if not supplier and result.get("VENDOR_NAME") and len(result.get("VENDOR_NAME").split(" ")) > 1:
			for substring in result.get("VENDOR_NAME").split(" "):
				supplier = frappe.db.get_value("Supplier", substring)
				if supplier:
					break

		return supplier