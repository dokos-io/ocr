from typing import TYPE_CHECKING
import frappe

from mistralai import Mistral


if TYPE_CHECKING:
	from ocr.ocr.doctype.ocr_request.ocr_request import OCRRequest

class MistralOCR:
	def __init__(self, doc: "OCRRequest"):
		ocr_settings = frappe.get_single("OCR Settings")
		self.client = Mistral(api_key=ocr_settings.get_password("mistral_api_key"))
		self.doc = doc
		self.file = frappe.get_doc("File", self.doc.file) if self.doc.file else frappe._dict()
		self.uploaded_file = None
		self.signed_url = None
		self.model = "mistral-ocr-latest"


	def upload_file(self):
		if not self.file:
			frappe.throw("No encoded file found")

		self.uploaded_file = self.client.files.upload(
			file={
				"file_name": self.file.file_name, # type: ignore
				"content": self.file.get_content(), # type: ignore
			},
			purpose="ocr"
		)

		return self.uploaded_file.id

	def get_signed_url(self, file_id):
		self.signed_url = self.client.files.get_signed_url(file_id=file_id)
		return self.signed_url

	def get_ocr_results(self, url):
		self.ocr_response = self.client.ocr.process(
			model=self.model,
			document={
				"type": "document_url",
				"document_url": url,
			},
			include_image_base64=True
		)
		return self.ocr_response
