"""SIRENE registry lookup (recherche-entreprises.api.gouv.fr).

Autofills party master data from the French company registry so users stop
hand-typing SIREN/SIRET/addresses (the top source of transposition errors that
only surface as PA rejections). The API is public and keyless (~7 req/s);
results are cached for 10 minutes per query.
"""

import frappe
from frappe import _

try:
	import requests
except ImportError:
	requests = None

SEARCH_URL = "https://recherche-entreprises.api.gouv.fr/search"
_CACHE_TTL = 600
_LOOKUP_ROLES = (
	"System Manager",
	"Accounts Manager",
	"Accounts User",
	"Sales Manager",
	"Sales User",
	"Purchase Manager",
	"Purchase User",
)


def fr_vat_from_siren(siren: str) -> str | None:
	"""Compute the French intra-community VAT number from a SIREN."""
	siren = (siren or "").replace(" ", "")
	if not (siren.isdigit() and len(siren) == 9):
		return None
	key = (12 + 3 * (int(siren) % 97)) % 97
	return f"FR{key:02d}{siren}"


@frappe.whitelist()
def search(query: str, limit: int = 8) -> list[dict]:
	"""Search the SIRENE registry by company name or SIREN/SIRET.

	Returns trimmed rows: name, siren, computed FR VAT, head-office SIRET and
	address, activity label and active flag.
	"""
	frappe.only_for(_LOOKUP_ROLES)
	query = (query or "").strip()
	if len(query) < 3:
		return []
	if not requests:
		frappe.throw(_("The 'requests' library is required for the SIRENE lookup."))

	limit = min(int(limit or 8), 20)
	cache_key = f"sirene_search:{query.lower()}:{limit}"
	cached = frappe.cache().get_value(cache_key)
	if cached is not None:
		return cached

	try:
		resp = requests.get(
			SEARCH_URL,
			params={"q": query, "per_page": limit, "page": 1},
			timeout=10,
		)
		resp.raise_for_status()
		payload = resp.json()
	except Exception:
		frappe.log_error(title="SIRENE search failed", message=frappe.get_traceback())
		frappe.throw(
			_("The SIRENE registry could not be reached. Try again later or fill the fields manually.")
		)

	results = [_trim(row) for row in payload.get("results") or []]
	frappe.cache().set_value(cache_key, results, expires_in_sec=_CACHE_TTL)
	return results


def _trim(row: dict) -> dict:
	siege = row.get("siege") or {}
	siren = row.get("siren")
	address_parts = [
		siege.get("numero_voie"),
		siege.get("type_voie"),
		siege.get("libelle_voie"),
	]
	address_line1 = " ".join(str(p) for p in address_parts if p) or siege.get("adresse")
	return {
		"name": row.get("nom_raison_sociale") or row.get("nom_complet"),
		"siren": siren,
		"tax_id": fr_vat_from_siren(siren),
		"siret": siege.get("siret"),
		"address_line1": address_line1,
		"pincode": siege.get("code_postal"),
		"city": siege.get("libelle_commune"),
		"activity": row.get("libelle_activite_principale") or (row.get("activite_principale") or ""),
		"active": (row.get("etat_administratif") or "A") == "A",
	}
