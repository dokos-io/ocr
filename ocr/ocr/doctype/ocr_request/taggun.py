import requests
import json

import frappe

class Taggun:
	def __init__(self, doc):
		self.url = "https://api.taggun.io/api/receipt/v1/verbose/file"
		self.doc = doc
		self.settings = frappe.get_single("OCR Settings")
		self.api_key = self.settings.get_password("taggun_api_key")

	def start_analysis(self):
		file = frappe.get_doc("File", self.doc.file)

		headers = {
			"Accept": "application/json",
			"apikey": self.api_key
			# "Content-Disposition": f'form-data; name=";File"; filename={file.file_name}'
		}

		files = {"file": (file.file_name, open(file.get_full_path(), "rb"), file.file_type)}

		response = requests.post(
			self.url,
			headers=headers,
			files=files,
			data={
				"extractLineItems": True
			}
		)

		return response.json()
