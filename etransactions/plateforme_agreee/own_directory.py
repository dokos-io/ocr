"""Manage the company's own e-invoicing directory entries.

Registering your company in a directory is the one place the Peppol vs French
(PPF) distinction is a real choice: the platform exposes a ``directory`` of
``"peppol"`` or ``"ppf"``.

Two implementations sit behind the same dialog:

* **SuperPDP** exposes native own-entry endpoints (capability
  ``directory_registration``).
* **Esalink** manages identifiers through the partner Customer API
  (capability ``directory_registration_via_partner``): requests are validated
  by Esalink and take effect at a start date ≥10 days out. Entries are keyed
  by ``qualifier:identifier`` instead of a numeric id.
"""

import frappe
from frappe import _

from etransactions.plateforme_agreee.session import (
	_build_client,
	_platform_credentials,
	platform_supports,
)


class EsalinkDirectoryAdapter:
	"""Adapts HUBTIMIZE's partner identifier API to the directory-dialog trio."""

	def __init__(self, customer_id: int, environment: str | None = None):
		from etransactions.plateforme_agreee.esalink_provisioning import _partner_client

		self.client = _partner_client(environment)
		self.customer_id = int(customer_id)

	def list_directory_entries(self) -> list[dict]:
		entries = []
		for row in self.client.search_identifiers(self.customer_id):
			qualifier = row.get("qualifier") or "0225"
			identifier = row.get("identifier") or ""
			entries.append(
				{
					"id": f"{qualifier}:{identifier}",
					"identifier": identifier,
					"directory": "ppf" if qualifier == "0225" else "peppol",
					"status": row.get("identifierStatus"),
					"is_replyto": None,
				}
			)
		return entries

	def create_directory_entry(self, identifier: str, directory: str) -> dict:
		from etransactions.plateforme_agreee.esalink_provisioning import _start_date

		qualifier, value = self._split(identifier, directory)
		row = self.client.create_identifier(
			self.customer_id,
			addressing_identifier=value,
			addressing_qualifier=qualifier,
			start_date=_start_date(),
		)
		return {
			"id": f"{qualifier}:{value}",
			"identifier": value,
			"directory": directory,
			"status": (row or {}).get("identifierStatus", "NEW"),
			"is_replyto": None,
		}

	def delete_directory_entry(self, entry_id) -> None:
		qualifier, _sep, identifier = str(entry_id).partition(":")
		if not identifier:
			frappe.throw(_("Invalid Esalink directory entry id: {0}").format(entry_id))
		self.client.delete_identifier(self.customer_id, identifier, qualifier)

	@staticmethod
	def _split(identifier: str, directory: str) -> tuple[str, str]:
		"""Split ``scheme:value`` into (qualifier, value); PPF defaults to 0225."""
		if ":" in identifier:
			qualifier, value = identifier.split(":", 1)
			return qualifier.strip(), value.strip()
		if directory == "peppol":
			frappe.throw(
				_(
					"A Peppol identifier must carry its scheme, e.g. 0088:1234567890123."
				)
			)
		return "0225", identifier.strip()


def _get_directory_client(platform_name: str):
	"""Build a directory-capable client (or adapter) for a saved platform.

	Mirrors the doc-fetch + ``_build_client`` pattern in
	``session.check_platform_health``; raises a clear message if the platform
	does not support directory registration.
	"""
	doc = frappe.get_cached_doc("eTransactions Accredited Platform", platform_name)

	if platform_supports(doc.platform_type, "directory_registration_via_partner"):
		if not doc.get("esalink_customer_id"):
			frappe.throw(
				_(
					"This Esalink platform has no customer account id yet. Provision the"
					" company on Esalink first (eTransactions Settings)."
				)
			)
		return EsalinkDirectoryAdapter(doc.esalink_customer_id, doc.esalink_environment)

	if not platform_supports(doc.platform_type, "directory_registration"):
		frappe.throw(
			_("Directory registration is not supported on {0} platforms.").format(doc.platform_type)
		)
	client_id, client_secret = _platform_credentials(doc)
	return _build_client(
		doc.platform_type,
		client_id,
		client_secret,
		api_base_url=doc.api_base_url,
		platform_code=doc.platform_code,
		sandbox=bool(doc.is_sandbox),
		auth_method=doc.get("auth_method") or "client_credentials",
		platform_name=platform_name,
		company=doc.company,
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
	entry_id = int(entry_id) if str(entry_id).isdigit() else entry_id
	client.delete_directory_entry(entry_id)
	return {"status": "ok"}
