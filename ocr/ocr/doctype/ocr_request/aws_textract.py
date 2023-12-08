import boto3
import io

from botocore.exceptions import ClientError

import frappe

class AWSTextract:
	def __init__(self, doc):
		self.settings = frappe.get_single("OCR Settings")
		self.client_key = self.settings.aws_textract_key or frappe.conf.aws_textract_key
		self.secret_key = self.settings.get_password("aws_textract_secret", raise_exception=False) or frappe.conf.aws_textract_secret

		self.textract_client = boto3.client(
			'textract',
			aws_access_key_id=self.client_key,
			aws_secret_access_key=self.secret_key,
			region_name="eu-west-3"
		)

		self.doc = doc
		self.bucket = frappe.conf.ocr_s3_bucket or frappe.local.site
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
			aws_access_key_id=self.client_key,
			aws_secret_access_key=self.secret_key,
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

		analysis["ParsedData"] = result
		return analysis