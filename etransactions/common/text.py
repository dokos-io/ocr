import hashlib
import os
from typing import Literal
# import posixpath
import frappe
import frappe.utils
from frappe.core.doctype.file.file import File
from subprocess import PIPE, Popen

_JS_FILE = os.path.join(os.path.dirname(__file__), "text.mjs")


def _ocr_run_command(cmd: list[str], stdin: bytes) -> bytes:
	process = Popen(cmd, cwd="/tmp", stdin=PIPE, stdout=PIPE, stderr=PIPE)
	res = process.communicate(input=stdin)

	stderr = res[1]
	if stderr:
		stderr = str(frappe.safe_decode(stderr))
		stderr = stderr.replace("\n", "<br>")
		frappe.throw(stderr)
	return res[0]


# def ocr_grab_path(file_name: str):
# 	folder_path: str = frappe.utils.get_files_path("etransactions", is_private=True)
# 	frappe.create_folder(posixpath.abspath(folder_path))
# 	file_name = file_name.strip("./")
# 	output_path = posixpath.join(folder_path, file_name)
# 	return output_path


def aws_textract_to_docx_and_attach(
		json_data: str,
		output_name: str,
		name = "",
		doctype = "",
		type: Literal["blocks", "lines"] = "lines",
		orientation: Literal["landscape", "portrait"] = "landscape",
		# size_mm: tuple[float, float] = (210, 297),
	):
	hashed = hashlib.md5(json_data.encode("utf-8")).hexdigest()[:8]

	if not output_name:
		output_name = "text"

	output_path = f"text_{hashed}.docx"
	file_name = os.path.basename(output_path)
	result = _ocr_run_command(["node", _JS_FILE, type, orientation], json_data.encode("utf-8"))

	# Create a File document
	file_doc: "File" = frappe.new_doc("File")  # type: ignore
	file_doc.is_private = True
	file_doc.file_name = file_name
	file_doc.content = result
	if name and doctype:
		file_doc.attached_to_name = name
		file_doc.attached_to_doctype = doctype
	file_doc.save()

	return file_doc
