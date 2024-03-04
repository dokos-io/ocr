from dataclasses import dataclass
from functools import cached_property
import operator
from typing import TYPE_CHECKING, Callable, Generic, TypeVar
import boto3
import io

from botocore.client import BaseClient
from botocore.exceptions import ClientError

import frappe
import frappe.utils

if TYPE_CHECKING:
	from ocr.ocr.doctype.ocr_request.ocr_request import OCRRequest
	from ocr.ocr.doctype.ocr_generic_text_transcription.ocr_generic_text_transcription import OCRGenericTextTranscription
	from frappe.core.doctype.file.file import File


@dataclass
class AwsAuthHandler:
	client_key: str
	secret_key: str
	on_error: Callable = operator.truth  # noop

	@classmethod
	def FromOcrSettings(cls, *args, **kwargs):
		settings = frappe.get_single("OCR Settings")
		client_key = settings.aws_textract_key or frappe.conf.aws_textract_key
		secret_key = settings.get_password("aws_textract_secret", raise_exception=False) or frappe.conf.aws_textract_secret
		return cls(client_key=client_key, secret_key=secret_key, *args, **kwargs)

@dataclass
class AwsFileHandlerBase:
	auth: AwsAuthHandler
	bucket: str
	key: str

	def upload(self):
		raise NotImplementedError

	def delete(self):
		raise NotImplementedError

	def get_location(self):
		return {"S3Object": {"Bucket": self.bucket, "Name": self.key}}

@dataclass
class AwsFileHandlerReadOnly(AwsFileHandlerBase):
	auth: AwsAuthHandler
	bucket: str
	key: str

	def upload(self):
		pass

	def delete(self):
		pass


@dataclass
class AwsFileHandler(AwsFileHandlerBase):
	auth: AwsAuthHandler
	bucket: str
	key: str
	content: bytes | None = None

	@cached_property
	def s3_client(self) -> "BaseClient":
		try:
			return boto3.client(
				's3',
				aws_access_key_id=self.auth.client_key,
				aws_secret_access_key=self.auth.secret_key,
				region_name="eu-west-3"
			)
		except Exception as e:
			self.auth.on_error(e)

	def _create_bucket(self):
		try:
			self.s3_client.head_bucket(Bucket=self.bucket)
		except ClientError:
			self.s3_client.create_bucket(
				Bucket=self.bucket,
				CreateBucketConfiguration={
					'LocationConstraint': 'eu-west-3'
				},
			)

	def upload(self):
		self._create_bucket()
		if self.content is None:
			if self.key.startswith("/"):
				file = frappe.get_doc("File", {"file_url": self.key})
			else:
				file = frappe.get_doc("File", self.key)
			content: bytes = file.get_content()  # type: ignore
		else:
			content = self.content

		self.s3_client.upload_fileobj(
			io.BytesIO(content),
			self.bucket,
			self.key,
		)

	def delete(self):
		self._create_bucket()
		self.s3_client.delete_object(
			Bucket=self.bucket,
			Key=self.key,
		)

	def get_location(self):
		return {"S3Object": {"Bucket": self.bucket, "Name": self.key}}


T = TypeVar("T")

@dataclass
class BaseAwsTaskHandler(Generic[T]):
	auth: AwsAuthHandler

	def __post_init__(self):
		self.job_id = None

	def hydrate(self, job: str):
		"""Hydrates the task handler with the job ID"""
		self.job_id = job

	def start(self) -> str:
		"""Returns the Job ID"""
		raise NotImplementedError

	def delete(self):
		"""Deletes the results of the job"""
		raise NotImplementedError

	def get_result(self) -> T | None:
		"""Returns the result of the job"""
		raise NotImplementedError


@dataclass
class AwsTextractTaskHandler(BaseAwsTaskHandler[dict]):
	file: AwsFileHandlerBase

	@cached_property
	def textract_client(self):
		return boto3.client("textract", aws_access_key_id=self.auth.client_key, aws_secret_access_key=self.auth.secret_key, region_name="eu-west-3")

	def start(self) -> str:
		if not self.job_id:
			self.file.upload()
			response = self._start_method(DocumentLocation=self.file.get_location())
			self.job_id = response.get("JobId")
		return self.job_id

	def delete(self):
		self.file.delete()

	def get_result(self):
		if analysis := self._get_merged_results():
			return self.postprocess_results(analysis)
		return None

	@cached_property
	def MERGED_KEYS(self):
		return ["Warnings"]

	def _fetch_method(self, *args, **kwargs):
		raise NotImplementedError

	def _fetch_results(self, paginationToken=None, maxResults=1000):
		if paginationToken:
			return self._fetch_method(JobId=self.job_id, MaxResults=maxResults, NextToken=paginationToken)
		else:
			return self._fetch_method(JobId=self.job_id, MaxResults=maxResults)

	def _iterate_results(self):
		paginationToken = None
		done = False
		while not done:
			response = self._fetch_results(paginationToken)
			paginationToken = response.get('NextToken')
			if not paginationToken:
				done = True
			yield response

	def _get_merged_results(self):
		try:
			result = {}
			for response in self._iterate_results():
				if not result:
					result = response
					continue

				# Merge responses
				for key in self.MERGED_KEYS:
					has_new_value = key in response and isinstance(result[key], list)
					has_old_value = key in result and isinstance(result[key], list)
					if has_new_value:
						if not has_old_value:
							result[key] = []
						result[key].extend(response[key])
			return result
		except ClientError as e:
			self.auth.on_error(e)

	def postprocess_results(self, analysis: dict) -> dict:
		return analysis


@dataclass
class AwsTextractExpenseAnalysis(AwsTextractTaskHandler):
	@cached_property
	def MERGED_KEYS(self):
		return ["ExpenseDocuments"] + super().MERGED_KEYS

	def _start_method(self, *args, **kwargs):
		return self.textract_client.start_expense_analysis(*args, **kwargs)

	def _fetch_method(self, *args, **kwargs):
		return self.textract_client.get_expense_analysis(*args, **kwargs)

	def postprocess_results(self, analysis):
		result = frappe._dict(_children=[])

		def set_val(field, out: dict):
			key = field["Type"].get("Text")
			value = field["ValueDetection"].get("Text")
			if key in out:
				if isinstance(out[key], list):
					out[key].append(value)
				else:
					return
			out[key] = value

		for expense in analysis.get("ExpenseDocuments") or []:
			for field in expense["SummaryFields"]:
				set_val(field, result)

			for line in expense["LineItemGroups"]:
				for item in line["LineItems"]:
					row = {}
					for field in item["LineItemExpenseFields"]:
						set_val(field, row)
					result._children.append(row)

		analysis["ParsedData"] = result
		return analysis


@dataclass
class AwsTextractTextDetection(AwsTextractTaskHandler):
	@cached_property
	def MERGED_KEYS(self):
		return ["Blocks"] + super().MERGED_KEYS

	def _start_method(self, *args, **kwargs):
		return self.textract_client.start_document_text_detection(*args, **kwargs)

	def _fetch_method(self, *args, **kwargs):
		return self.textract_client.get_document_text_detection(*args, **kwargs)


class AWSTextract:
	@cached_property
	def bucket(self):
		return frappe.conf.ocr_s3_bucket or frappe.local.site

	@cached_property
	def auth(self):
		return AwsAuthHandler.FromOcrSettings(on_error=self.on_error)

	def on_error(self, e: Exception):
		raise e


class AWSTextractExpense(AWSTextract):
	def __init__(self, doc: "OCRRequest"):
		self.doc = doc

		self.file = AwsFileHandler(auth=self.auth, bucket=self.bucket, key=self.doc.file)
		self.task = AwsTextractExpenseAnalysis(auth=self.auth, file=self.file)

		if self.doc.job:
			self.task.hydrate(self.doc.job)

	def on_error(self, e: Exception):
		self.doc.db_set("status", "Error")
		self.doc.db_set("error", str(e) + "\n" + frappe.utils.get_traceback())
		raise e


class AWSTextractText(AWSTextract):
	def __init__(self, doc: "OCRGenericTextTranscription"):
		self.doc = doc
		if not self.doc.file:
			raise ValueError("File not found")

		file_doc: "File" = frappe.get_doc("File", {"file_url": self.doc.file})  # type: ignore
		uuid = "-".join(map(str, (self.doc.doctype, self.doc.name, file_doc.file_name)))
		self.file = AwsFileHandler(auth=self.auth, bucket=self.bucket, key=uuid, content=file_doc.get_content())
		self.task = AwsTextractTextDetection(auth=self.auth, file=self.file)
		if self.doc.task:
			self.task.hydrate(self.doc.task)
		else:
			task_id = self.task.start()
			self.doc.db_set("task", task_id, update_modified=False, commit=True, notify=True)

	def start(self):
		return self.task.start()

	def get_result(self):
		try:
			return self.task.get_result()
		except ClientError as e:
			if "InvalidJobIdException" in e.args[0]:
				self.doc.db_set("task", "")
				return None

	def delete(self):
		return self.task.delete()
