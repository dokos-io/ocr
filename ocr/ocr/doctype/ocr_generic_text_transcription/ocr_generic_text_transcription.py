# Copyright (c) 2024, Dokos SAS and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from ocr.common.text import aws_textract_to_docx_and_attach
from ocr.ocr.doctype.ocr_request.aws_textract import AWSTextractText

class OCRGenericTextTranscription(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		attached_to_doctype: DF.Link | None
		attached_to_name: DF.DynamicLink | None
		file: DF.Attach | None
		status: DF.Literal["Pending", "Transcribing", "Transcribed", "Processing", "Processed", "Completed", "Error"]
		task: DF.Data | None
		task_results: DF.JSON | None
	# end: auto-generated types

	def validate(self):
		if not self.attached_to_name or not self.attached_to_doctype:
			self.attached_to_name = self.name
			self.attached_to_doctype = self.doctype

		if not self.status or self.status in ("Draft", "Error"):
			self.status = "Pending"

	def after_insert(self):
		self.queue_tick()

	def ocr_set_status(self, status: str):
		self.db_set("status", status, update_modified=False, commit=True, notify=True)

	def queue_tick(self):
		frappe.enqueue_doc(self.doctype, self.name, "tick", queue="short", enqueue_after_commit=True)

	def tick(self):
		try:
			self._tick()
		except Exception:
			self.ocr_set_status("Error")
			self.log_error()
			frappe.msgprint("An error occurred while processing the OCR request")

	def _tick(self):
		if self.status == "Completed":
			return

		is_done_ocr = bool(self.task_results)
		if is_done_ocr:
			if self.status == "Processing":
				return
			assert self.name and self.doctype and self.task_results and self.attached_to_name and self.attached_to_doctype
			self.ocr_set_status("Processing")
			file_doc = aws_textract_to_docx_and_attach(
				json_data=self.task_results,
				output_name=self.name,
				name=self.attached_to_name,
				doctype=self.attached_to_doctype,
			)
			if file_doc:
				self.ocr_set_status("Completed")
			else:
				raise Exception("Could not create DOCX file")
			return  # End branch

		if self.file:
			if self.status == "Transcribed":
				return

			service = frappe.db.get_single_value("OCR Settings", "selected_ocr_service")
			if service == "AWS Textract":
				textract = AWSTextractText(self)
			else:
				return

			job_data = textract.get_result()
			if job_data and job_data.get("JobStatus") == "IN_PROGRESS":
				if self.status != "Transcribing":
					return self.ocr_set_status("Transcribing")
			elif job_data and job_data.get("JobStatus") == "SUCCEEDED":
				self.db_set(
					{
						"task_results": frappe.as_json(job_data, indent=0, ensure_ascii=False),
						"status": "Transcribed",
					},
					update_modified=True,
					commit=True,
				)
				textract.delete()
				self.queue_tick()
			return  # End branch

@frappe.whitelist()
def tick(doc: str):
	ocr_doc: "OCRGenericTextTranscription" = frappe.get_doc(
		"OCR Generic Text Transcription",
		frappe.parse_json(doc).name,  # type: ignore
	)  # type: ignore
	ocr_doc.queue_tick()

	return ocr_doc
