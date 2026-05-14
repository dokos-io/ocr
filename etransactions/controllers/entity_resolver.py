import re
import frappe
import difflib

LEGAL_FORMS = frozenset({
	"SA", "SAS", "SARL", "EURL", "SCI", "SNC", "GIE", "SASU",
	"SELARL", "SELAFA", "SCOP", "SCP", "SEP",
})
STOP_WORDS = frozenset({"ET", "DE", "DU", "LA", "LE", "LES", "DES", "EN", "AU", "AUX"})


class InvoiceEntityResolverMixin:
	"""Shared logic for resolving Supplier and Company records from raw text."""

	def _normalize_tax_id(self, tax_id: str) -> str:
		return re.sub(r"[\s\-\.]", "", tax_id).upper() if tax_id else ""

	def _strip_legal_forms(self, name: str) -> str:
		pattern = r"\b(" + "|".join(re.escape(f) for f in LEGAL_FORMS) + r")\b"
		return re.sub(pattern, "", name, flags=re.IGNORECASE).strip()

	def resolve_supplier(self, seller_name: str, tax_id: str = None, iban: str = None) -> str:
		supplier = None
		self._match_confidence = "low"

		# 1. Match by normalized Tax ID
		if tax_id:
			normalized = self._normalize_tax_id(tax_id)
			supplier = frappe.db.get_value("Supplier", {"tax_id": normalized})
			if not supplier:
				for s in frappe.get_all(
					"Supplier",
					filters={"disabled": 0, "tax_id": ("is", "set")},
					fields=["name", "tax_id"],
				):
					if self._normalize_tax_id(s.tax_id) == normalized:
						supplier = s.name
						break
			if supplier:
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
		if not supplier and seller_name:
			alias_supplier = frappe.db.get_value(
				"eTransactions Supplier Name Alias", {"vendor_name": seller_name}, "supplier"
			)
			if alias_supplier:
				supplier = alias_supplier
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