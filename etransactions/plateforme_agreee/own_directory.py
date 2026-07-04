"""Manage the company's own e-invoicing directory entries.

Registering your company in a directory is the one place the Peppol vs French
(PPF) distinction is a real choice: the platform exposes a ``directory`` of
``"peppol"`` or ``"ppf"``. Only SuperPDP supports this today (gated by the
``directory_registration`` capability); CDAR platforms register through their
own portal.

These endpoints are driven by the "Directory registration" dialog on the
eTransactions Accredited Platform form.
"""

import frappe
from frappe import _

from etransactions.plateforme_agreee.session import _build_client, platform_supports


def _get_directory_client(platform_name: str):
	"""Build a directory-capable client for a saved platform.

	Mirrors the doc-fetch + ``_build_client`` pattern in
	``session.check_platform_health``; raises a clear message if the platform
	does not support directory registration.
	"""
	doc = frappe.get_cached_doc("eTransactions Accredited Platform", platform_name)
	if not platform_supports(doc.platform_type, "directory_registration"):
		frappe.throw(
			_("Directory registration is not supported on {0} platforms.").format(doc.platform_type)
		)
	return _build_client(
		doc.platform_type,
		doc.get_password("client_id"),
		doc.get_password("client_secret", raise_exception=False),
		api_base_url=doc.api_base_url,
		platform_code=doc.platform_code,
		sandbox=bool(doc.is_sandbox),
		auth_method=doc.get("auth_method") or "client_credentials",
		platform_name=platform_name,
	)


def _trim(entry: dict) -> dict:
	"""Keep only the fields the dialog needs (no secrets)."""
	return {
		"id": entry.get("id"),
		"identifier": entry.get("identifier"),
		"directory": entry.get("directory"),
		"status": entry.get("status"),
		"is_replyto": entry.get("is_replyto"),
	}


@frappe.whitelist()
def list_directory_entries(platform_name: str) -> list[dict]:
	"""Return the company's own directory entries for a platform."""
	frappe.only_for(("System Manager", "Accounts Manager"))
	client = _get_directory_client(platform_name)
	return [_trim(e) for e in client.list_directory_entries()]


@frappe.whitelist()
def register_directory_entry(platform_name: str, identifier: str, directory: str) -> dict:
	"""Register a new directory entry, choosing the directory (Peppol / PPF)."""
	frappe.only_for(("System Manager", "Accounts Manager"))
	identifier = (identifier or "").strip()
	if not identifier:
		frappe.throw(_("An identifier is required (e.g. 0225:123456789)."))
	if directory not in ("peppol", "ppf"):
		frappe.throw(_("Directory must be either 'peppol' or 'ppf'."))
	client = _get_directory_client(platform_name)
	return _trim(client.create_directory_entry(identifier, directory))


@frappe.whitelist()
def remove_directory_entry(platform_name: str, entry_id) -> dict:
	"""Remove one of the company's directory entries by id."""
	frappe.only_for(("System Manager", "Accounts Manager"))
	client = _get_directory_client(platform_name)
	client.delete_directory_entry(int(entry_id))
	return {"status": "ok"}
