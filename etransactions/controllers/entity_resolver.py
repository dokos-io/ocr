import re
import frappe
import difflib

from frappe import _

LEGAL_FORMS = frozenset({
	"SA", "SAS", "SARL", "EURL", "SCI", "SNC", "GIE", "SASU",
	"SELARL", "SELAFA", "SCOP", "SCP", "SEP",
})
STOP_WORDS = frozenset({"ET", "DE", "DU", "LA", "LE", "LES", "DES", "EN", "AU", "AUX"})

# Below this, a vendor name is a fragment rather than an identity ("SSP", "V-").
MIN_LEARNABLE_VENDOR_NAME_LENGTH = 4
# A name this close to one of our own companies is the buyer, whatever OCR labelled it.
OWN_COMPANY_SIMILARITY = 0.85


def normalize_vendor_name(name: str | None) -> str:
	"""Collapse the whitespace OCR inherits from the PDF's line breaks.

	Textract returns the vendor block verbatim, so the same supplier arrives as
	"Tete en\nl'air" on one invoice and "Tete en l'air" on the next. Aliases keyed on the
	raw string would treat those as two different vendors.
	"""
	return re.sub(r"\s+", " ", name or "").strip()


def is_own_company_name(name: str | None) -> bool:
	"""True when the name denotes one of our own companies rather than a supplier.

	OCR routinely reads the buyer's letterhead as VENDOR_NAME. Learning that as a supplier
	alias maps our own name onto whichever supplier was being corrected at the time, and
	every later misread then resolves to that supplier with high confidence.
	"""
	candidate = normalize_vendor_name(name).lower()
	if not candidate:
		return False

	for company, abbr in frappe.get_all("Company", fields=["name", "abbr"], as_list=True):
		# The abbreviation is only trusted on an exact match: it is often two letters, and
		# "DK" as a substring rule would swallow real suppliers.
		if candidate in {normalize_vendor_name(company).lower(), normalize_vendor_name(abbr).lower()}:
			return True

		own = normalize_vendor_name(company).lower()
		if len(own) < MIN_LEARNABLE_VENDOR_NAME_LENGTH:
			continue
		# "DOKOS SAS", "SAS DOKOS" — the legal form is noise around our own name.
		if own in candidate.split():
			return True
		if difflib.SequenceMatcher(None, candidate, own).ratio() >= OWN_COMPANY_SIMILARITY:
			return True

	return False


def vendor_name_rejection_reason(name: str | None) -> str | None:
	"""Why this vendor name may not be learned as an alias, or None if it may.

	Resolution trusts the alias table at "high" confidence, ahead of every similarity
	heuristic, so a row that does not identify exactly one supplier actively misroutes
	invoices instead of merely failing to help.
	"""
	candidate = normalize_vendor_name(name)

	if len(candidate) < MIN_LEARNABLE_VENDOR_NAME_LENGTH or not any(c.isalpha() for c in candidate):
		return _("{0} is too generic to identify a supplier.").format(candidate)

	if is_own_company_name(candidate):
		return _("{0} is one of your own companies, not a supplier name.").format(candidate)

	return None


def is_learnable_vendor_name(name: str | None) -> bool:
	"""Whether a vendor name is specific enough to be worth remembering as an alias."""
	return vendor_name_rejection_reason(name) is None


class InvoiceEntityResolverMixin:
	"""Shared logic for resolving Supplier and Company records from raw text."""

	def _normalize_tax_id(self, tax_id: str) -> str:
		return re.sub(r"[\s\-\.]", "", tax_id).upper() if tax_id else ""

	def _company_tax_ids(self) -> set:
		"""Normalized VAT/tax ids of our own companies (the buyer side).

		A supplier invoice must never resolve a supplier from the buyer's own VAT,
		which OCR frequently mistakes for the seller's (e.g. AWS Textract TAX_PAYER_ID).
		"""
		ids = frappe.get_all("Company", filters={"tax_id": ("is", "set")}, pluck="tax_id")
		return {self._normalize_tax_id(t) for t in ids if t}

	def _strip_legal_forms(self, name: str) -> str:
		pattern = r"\b(" + "|".join(re.escape(f) for f in LEGAL_FORMS) + r")\b"
		return re.sub(pattern, "", name, flags=re.IGNORECASE).strip()

	def resolve_supplier(self, seller_name: str, tax_id: str = None, iban: str = None) -> str:
		supplier = None
		self._match_confidence = "low"

		# 1. Match by normalized Tax ID — only when unambiguous and not the buyer's own VAT.
		# A tax_id shared by several suppliers (usually because a buyer VAT leaked onto
		# masters) must not be trusted: we fall through to name-based matching instead of
		# arbitrarily picking one supplier and reporting high confidence.
		if tax_id:
			normalized = self._normalize_tax_id(tax_id)
			if normalized and normalized not in self._company_tax_ids():
				matches = [
					s.name
					for s in frappe.get_all(
						"Supplier",
						filters={"disabled": 0, "tax_id": ("is", "set")},
						fields=["name", "tax_id"],
					)
					if self._normalize_tax_id(s.tax_id) == normalized
				]
				if len(matches) == 1:
					supplier = matches[0]
					self._match_confidence = "high"

		# 2. Match by IBAN via Bank Account
		if not supplier and iban:
			normalized_iban = re.sub(r"\s", "", iban).upper()
			bank_account = frappe.db.get_value(
				"Bank Account",
				{"iban": normalized_iban, "party_type": "Supplier"},
				"party",
			)
			if bank_account:
				supplier = bank_account
				self._match_confidence = "high"

		# 3. Match by vendor name alias (manually confirmed mappings)
		# Same rule as the tax id above: an alias claimed by several suppliers is evidence of
		# a bad mapping, not of a match. Picking one arbitrarily — and calling it "high"
		# confidence — is how an OCR misread of the buyer's own name silently reassigns every
		# invoice bearing it. Fall through to name matching instead.
		if not supplier and seller_name:
			alias_suppliers = set(
				frappe.get_all(
					"eTransactions Supplier Name Alias",
					filters={"vendor_name": normalize_vendor_name(seller_name)},
					pluck="supplier",
				)
			)
			if len(alias_suppliers) == 1:
				supplier = alias_suppliers.pop()
				self._match_confidence = "high"

		# 4. Exact supplier_name match (also try name field for non-series naming)
		if not supplier and seller_name:
			supplier = frappe.db.get_value("Supplier", {"supplier_name": seller_name})
			if not supplier:
				supplier = frappe.db.get_value("Supplier", seller_name)
			if supplier:
				self._match_confidence = "high"

		# 5. Substring match with blocklist (min 4 chars, no legal forms or stop words)
		if not supplier and seller_name and len(seller_name.split(" ")) > 1:
			for substring in seller_name.split(" "):
				upper = substring.upper()
				if len(substring) >= 4 and upper not in LEGAL_FORMS and upper not in STOP_WORDS:
					if s := frappe.db.get_value("Supplier", {"supplier_name": substring}):
						supplier = s
						self._match_confidence = "low"
						break

		# 6. Fuzzy match with legal form stripping (cutoff 0.75, gap ≥ 0.10 for unambiguous match)
		if not supplier and seller_name:
			existing_suppliers = frappe.get_all(
				"Supplier", filters={"disabled": 0}, fields=["name", "supplier_name"]
			)
			stripped_query = self._strip_legal_forms(seller_name).lower()
			stripped_map = {
				s.name: self._strip_legal_forms(s.supplier_name or "").lower()
				for s in existing_suppliers
				if s.supplier_name
			}
			if stripped_map:
				scores = sorted(
					(
						(name, difflib.SequenceMatcher(None, stripped_query, stripped).ratio())
						for name, stripped in stripped_map.items()
					),
					key=lambda x: x[1],
					reverse=True,
				)
				best_name, best_score = scores[0]
				second_score = scores[1][1] if len(scores) > 1 else 0.0
				if best_score >= 0.75 and (best_score - second_score) >= 0.10:
					supplier = best_name
					self._match_confidence = "high" if best_score >= 0.90 else "medium"

		if supplier and frappe.db.exists("Supplier", supplier):
			return supplier

		self._match_confidence = "low"
		return ""

	def resolve_company(self, receiver_name: str, receiver_address: str = "") -> str:
		company = None
		companies_list = frappe.get_all("Company", pluck="name")
		companies_map = {c.lower(): c for c in companies_list}
		
		r_name = (receiver_name or "").lower()
		r_addr = (receiver_address or "").lower()

		# 1. Fuzzy Match Name
		if match := difflib.get_close_matches(r_name, list(companies_map.keys()), cutoff=0.9):
			company = companies_map[match[0]]

		# 2. Fuzzy Match Address
		if not company and (match := difflib.get_close_matches(r_addr, list(companies_map.keys()), cutoff=0.9)):
			company = companies_map[match[0]]

		# 3. Substring Containment
		if not company:
			for c_lower, c_orig in companies_map.items():
				if c_lower in r_name or c_lower in r_addr:
					company = c_orig
					break

		# 4. Fallback to single company
		if not company and len(companies_list) == 1:
			company = companies_list[0]

		return company or ""