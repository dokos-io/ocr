"""Resolve which e-invoicing routing line (and thus addressing identifier) to
use for a transaction.

A French legal entity (one SIREN) can hold many establishments (SIRET) and many
service / routing codes — i.e. many ``eInvoicing Directory Line`` rows. The
routing target of an invoice is therefore an *establishment*, which in ERPNext
maps naturally to an ``Address``. This module:

* parses the platform addressing identifier (Peppol ``<scheme>:<value>`` or PPF
  ``SIREN`` / ``SIREN_SIRET`` / ``SIREN_SUFFIXE``) into SIREN / SIRET / routing
  code (:func:`parse_directory_identifier`), and
* picks the right directory line for a (party, address) pair
  (:func:`resolve_routing`), with a deterministic fallback chain so the
  generator and the CDAR builder never diverge.
"""

import frappe


def parse_directory_identifier(identifier: str) -> dict:
	"""Best-effort split of a directory addressing identifier.

	Returns a dict with ``siren`` / ``siret`` / ``routing_code`` / ``line_type``
	(``line_type`` is one of ``siren`` / ``siret`` / ``routing_code``). Unknown
	parts are left as ``None``.
	"""
	out = {"siren": None, "siret": None, "routing_code": None, "line_type": None}
	if not identifier:
		return out

	value = identifier.strip()
	if ":" in value:  # Peppol form '<scheme>:<value>'
		value = value.split(":", 1)[1].strip()

	parts = value.split("_")
	digits = ["".join(c for c in p if c.isdigit()) for p in parts]
	head = digits[0] if digits else ""

	if len(head) == 14:  # SIRET held in the first token
		out["siret"] = head
		out["siren"] = head[:9]
		out["line_type"] = "siret"
	elif len(head) >= 9:
		out["siren"] = head[:9]
		out["line_type"] = "siren"

	if len(parts) > 1:
		tail = parts[1].strip()
		tail_digits = digits[1]
		if len(tail_digits) == 14:
			out["siret"] = tail_digits
			out["siren"] = out["siren"] or tail_digits[:9]
			out["line_type"] = "siret"
		elif len(tail_digits) == 5 and out["siren"]:  # NIC -> SIRET = SIREN + NIC
			out["siret"] = out["siren"] + tail_digits
			out["line_type"] = "siret"
		elif tail:
			out["routing_code"] = tail
			out["line_type"] = "routing_code"

	if not out["line_type"]:
		out["routing_code"] = value
		out["line_type"] = "routing_code"

	return out


def identifier_to_electronic_address(identifier: str) -> tuple[str, str]:
	"""Split a directory identifier into a (scheme, value) electronic address.

	Peppol identifiers carry the ISO 6523 scheme as a prefix (``0225:853322915``);
	bare PPF identifiers default to the French SIRENE scheme ``0225``.
	"""
	if not identifier:
		return "", ""
	if ":" in identifier:
		scheme, value = identifier.split(":", 1)
		return scheme.strip(), value.strip()
	return "0225", identifier.strip()


def address_for_siret(party_type: str, party: str, siret: str | None) -> str | None:
	"""Return the name of the party's Address whose SIRET matches ``siret``."""
	if not (siret and party_type and party):
		return None
	address_names = frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "Address", "link_doctype": party_type, "link_name": party},
		pluck="parent",
	)
	if not address_names:
		return None
	return frappe.db.get_value("Address", {"name": ["in", address_names], "siret": siret}, "name")


def resolve_routing(party_type: str, party: str | None, address: str | None = None):
	"""Pick the directory line to route to for a (party, address) pair.

	Resolution order:

	1. the active line bound to ``address`` (the invoice's establishment);
	2. the party's ``default_directory_line`` (if still active);
	3. the single active line, when the party has exactly one — unambiguous;
	4. otherwise ``None`` (caller falls back to the manual BT-34/BT-49 address).

	Returns the ``eInvoicing Directory Line`` name, or ``None``.
	"""
	if not (party_type and party):
		return None

	party_field = "customer" if party_type == "Customer" else "supplier"

	if address:
		line = frappe.db.get_value(
			"eInvoicing Directory Line",
			{party_field: party, "address": address, "line_status": "active"},
			"name",
		)
		if line:
			return line

	if party_type == "Customer":
		default_line = frappe.db.get_value("Customer", party, "default_directory_line")
		if default_line and frappe.db.get_value(
			"eInvoicing Directory Line", default_line, "line_status"
		) == "active":
			return default_line

	active = frappe.get_all(
		"eInvoicing Directory Line",
		filters={party_field: party, "line_status": "active"},
		pluck="name",
		limit=2,
	)
	if len(active) == 1:
		return active[0]

	return None
