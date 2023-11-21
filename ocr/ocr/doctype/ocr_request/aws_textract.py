import re
import boto3
import io
import difflib

from botocore.exceptions import ClientError
from dateutil.parser import parse

import frappe

# https://docs.python.org/3/library/re.html#simulating-scanf
FLOAT_PATTERN = re.compile(r"[-+]?(\d+([.,]\d*)?|[.,]\d+)([eE][-+]?\d+)?")

class AWSTextract:
	def __init__(self, doc):
		self.textract_client = boto3.client(
			'textract',
			aws_access_key_id=frappe.conf.aws_textract_key,
			aws_secret_access_key=frappe.conf.aws_textract_secret,
			region_name="eu-west-3"
		)

		self.doc = doc
		self.bucket = frappe.conf.ocr_s3_bucket or "dokos-ocr"
		self.s3_client = None

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
		self.create_bucket()
		self.upload_file()

	def init_s3_client(self):
		if self.s3_client:
			return

		self.s3_client = boto3.client(
			's3',
			aws_access_key_id=frappe.conf.aws_textract_key,
			aws_secret_access_key=frappe.conf.aws_textract_secret,
			region_name="eu-west-3"
		)

	def create_bucket(self):
		try:
			self.init_s3_client()
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
		self.init_s3_client()
		self.s3_client.upload_fileobj(
			io.BytesIO(file.get_content()),
			self.bucket,
			self.doc.filename
		)

	def delete_file(self):
		self.init_s3_client()
		self.s3_client.delete_object(
			Bucket=self.bucket,
			Key=self.doc.filename,
		)

	def get_analysis(self):
		if analysis := self._get_analysis_from_textract():
			return self.parse_analysis(analysis)
		return []

	def _get_analysis_from_textract(self):
		try:
			result = {}
			paginationToken = None
			done = False
			maxResults = 1000

			while done is False:

				if paginationToken:
					response = self.textract_client.get_expense_analysis(JobId=self.doc.job, MaxResults=maxResults, NextToken=paginationToken)
				else:
					response = self.textract_client.get_expense_analysis(JobId=self.doc.job, MaxResults=maxResults)

				if not result:
					result = response
				elif "ExpenseDocuments" in result:
					result["ExpenseDocuments"].extend(response.get("ExpenseDocuments", []))

				if not (paginationToken := response.get('NextToken')):
					done = True

			return result

		except ClientError as e:
			frappe.db.set_value(self.doc.doctype, self.doc.name, "status", "Error")
			frappe.db.set_value(self.doc.doctype, self.doc.name, "error", str(e))

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

		analysis["ParsedTextractData"] = result
		analysis["ParsedDokosData"] = self.get_purchase_invoice_data(result)
		return analysis

	def get_purchase_invoice_data(self, result):
		purchase_invoice = frappe._dict(items=[])
		purchase_invoice["vendor_name"] = result.get("VENDOR_NAME")
		purchase_invoice["supplier"] = self.get_supplier_name(result)
		purchase_invoice["bill_no"] = result.get("INVOICE_RECEIPT_ID")

		bill_date = None

		try:
			bill_date = parse(result.get("INVOICE_RECEIPT_DATE"))
		except Exception:
			pass

		purchase_invoice["bill_date"] = bill_date

		for child in result._children:
			if not child.get("ITEM"):
				continue

			item_code = self.get_supplier_item(purchase_invoice["supplier"], child.get("ITEM")) if purchase_invoice["supplier"] else None
			purchase_invoice["items"].append(
				{
					"item_code": item_code,
					"item_name": str(child.get("ITEM"))[:140],
					"description": child.get("EXPENSE_ROW") or child.get("ITEM"),
					"qty": self.get_first_floats(child.get("QUANTITY")) or 1,
					"rate": self.get_first_floats(child.get("UNIT_PRICE") or (child.get("QUANTITY") == 1 and child.get("PRICE"))),
					"description": child["EXPENSE_ROW"]
				}
			)

		return purchase_invoice

	def get_first_floats(self, data):
		if data and (matching_floats := FLOAT_PATTERN.findall(data)):
			for matching_float in matching_floats[0]:
				try:
					if matching_float:
						value = matching_float.replace(" ", "").replace(",", ".") # Temporary hack to parse floats in french invoices. To be enhanced with different number formats.
						return float(value) 
				except Exception:
					continue

		return data

	def get_supplier_name(self, result):
		supplier = None
		if result.get("VENDOR_VAT_NUMBER"):
			supplier = frappe.db.get_value("Supplier", dict(tax_id=result.get("VENDOR_VAT_NUMBER")))

		if not supplier and result.get("VENDOR_NAME"):
			supplier = frappe.db.get_value("Supplier", result.get("VENDOR_NAME"))

			if not supplier:
				self.get_value_from_mapping("VENDOR_NAME", result.get("VENDOR_NAME"), "Supplier")

		if not supplier and result.get("VENDOR_NAME") and len(result.get("VENDOR_NAME").split(" ")) > 1:
			for substring in result.get("VENDOR_NAME").split(" "):
				supplier = frappe.db.get_value("Supplier", substring)
				if supplier:
					break

		if not supplier and result.get("VENDOR_NAME"):
			existing_supplier_list = frappe.get_all("Supplier", filters=dict(disabled=0), pluck="supplier_name")
			sorted_suppliers = sorted(
				existing_supplier_list,
				key=lambda doc: difflib.SequenceMatcher(
					lambda doc: doc == " ", doc, result.get("VENDOR_NAME")
				).ratio(),
				reverse=True,
			)

			best_match = sorted_suppliers[0]

			if difflib.SequenceMatcher(lambda doc: doc == " ", best_match, result.get("VENDOR_NAME")).ratio() > 0.4:
				supplier = sorted_suppliers[0]

		if result.get("VENDOR_NAME"):
			self.register_key_mapping("VENDOR_NAME", result.get("VENDOR_NAME"), "Supplier", supplier)

		return supplier

	def get_value_from_mapping(self, key, value, reference_doctype):
		return frappe.db.get_value(
			"OCR Mapping",
			dict(
				ocr_service="AWS Textract",
				key=key,
				value=value,
				reference_doctype=reference_doctype
			),
			"reference_name"
		)

	def register_key_mapping(self, key, value, reference_doctype, reference_name):
		if existing_mapping := frappe.db.exists("OCR Mapping", dict(
			ocr_service="AWS Textract",
			key=key,
			value=value
		)):
			frappe.db.set_value("OCR Mapping", existing_mapping, dict(
				reference_doctype=reference_doctype,
				reference_name=reference_name
			))

		else:
			ocr_mapping = frappe.new_doc("OCR Mapping")
			ocr_mapping.ocr_service = "AWS Textract"
			ocr_mapping.key = key
			ocr_mapping.value = value
			ocr_mapping.reference_doctype = reference_doctype
			ocr_mapping.reference_name = reference_name
			ocr_mapping.insert()


	def get_supplier_item(self, supplier, item):
		return frappe.db.get_value(
			"Item Supplier",
			dict(
				supplier=supplier,
				supplier_part_no=item
			),
			"parent"
		)