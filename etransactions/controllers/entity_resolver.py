import re
import frappe
import difflib
import unicodedata
from collections import defaultdict

from frappe import _

LEGAL_FORMS = frozenset({
	"SA", "SAS", "SARL", "EURL", "SCI", "SNC", "GIE", "SASU",
	"SELARL", "SELAFA", "SCOP", "SCP", "SEP",
})
STOP_WORDS = frozenset({"ET", "DE", "DU", "LA", "LE", "LES", "DES", "EN", "AU", "AUX"})

# Address words that do not tell one street from another
STREET_WORDS = frozenset({
	"rue", "avenue", "chemin", "impasse", "route", "boulevard", "place", "allee", "zone", "quartier",
	"lieu", "dit", "cedex", "france",
})
# A Company abbreviation shorter than this ("VS") is too common to identify a buyer
MIN_COMPANY_ALIAS_LENGTH = 3
# Fuzzy buyer name match, as for suppliers: a close best match, clearly ahead of the second one
COMPANY_SIMILARITY = 0.85
COMPANY_SIMILARITY_GAP = 0.10

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


def normalize_tax_id(tax_id: str | None) -> str:
	return re.sub(r"[\s\-\.]", "", tax_id).upper() if tax_id else ""


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
		return normalize_tax_id(tax_id)

	def _company_tax_ids(self) -> set:
		"""Normalized VAT/tax ids of our own companies (the buyer side).

		A supplier invoice must never resolve a supplier from the buyer's own VAT,
		which OCR frequently mistakes for the seller's (e.g. AWS Textract TAX_PAYER_ID).
		"""
		ids = frappe.get_all("Company", filters={"tax_id": ("is", "set")}, pluck="tax_id")
		return {self._normalize_tax_id(t) for t in ids if t}

	def _strip_legal_forms(self, name: str) -> str:
		return strip_legal_forms(name)

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

def strip_legal_forms(name: str) -> str:
	pattern = r"\b(" + "|".join(re.escape(f) for f in LEGAL_FORMS) + r")\b"
	return re.sub(pattern, "", name, flags=re.IGNORECASE).strip()


def canonical_company(value: str | None) -> str | None:
	"""The Company's stored name for ``value``, or None if no Company matches.

	MariaDB compares names case- and accent-insensitively, so "VITRERIE STEPHANOISE"
	finds "Vitrerie Stéphanoise". A Link field must still hold the stored spelling:
	user permissions and every later lookup compare it byte for byte.
	"""
	if not value:
		return None
	return frappe.db.get_value("Company", value, "name")


def party_siren_candidates(
	siren: str | None = None,
	tax_id: str | None = None,
	electronic_address: str | None = None,
	electronic_address_scheme: str | None = None,
) -> set[str]:
	"""Every SIREN an invoice party can be identified by."""
	candidates = set()

	def add(digits: str) -> None:
		if len(digits) in (9, 14):  # SIREN, or SIRET whose first 9 digits are the SIREN
			candidates.add(digits[:9])

	add(_digits(siren))

	if (electronic_address_scheme or "").strip() in ("0009", "0225"):
		add(_digits(electronic_address))

	tax_id = normalize_tax_id(tax_id)
	if tax_id.startswith("FR") and len(_digits(tax_id)) == 11:
		# French VAT: FR + 2-character key + SIREN
		candidates.add(_digits(tax_id)[2:])
	else:
		add(_digits(tax_id))

	return candidates


def resolve_buyer_company(
	buyer_name: str | None,
	siren: str | None = None,
	tax_id: str | None = None,
	electronic_address: str | None = None,
	electronic_address_scheme: str | None = None,
	address: str | None = None,
	use_default: bool = True,
) -> str | None:
	"""Find which of our companies an incoming invoice is addressed to.

	Identifiers come first: the buyer name is printed however the supplier typed it
	("MIROITERIE AVIGNONNAISE"), while the SIREN and VAT number are exact. Each step
	only accepts a single match. Returns the stored Company name, or None.

	With ``use_default`` off, the site's default company is not used as a last resort.
	"""
	companies = frappe.get_all("Company", fields=["name", "company_name", "abbr", "siren_number", "tax_id"])

	sirens = party_siren_candidates(siren, tax_id, electronic_address, electronic_address_scheme)
	if sirens and (company := _single(c for c in companies if _digits(c.siren_number)[:9] in sirens)):
		return company

	normalized_tax_id = normalize_tax_id(tax_id)
	if normalized_tax_id and (
		company := _single(c for c in companies if normalize_tax_id(c.tax_id) == normalized_tax_id)
	):
		return company

	folded = _fold(buyer_name)
	if folded and (
		company := _single(c for c in companies if folded in (_fold(c.name), _fold(c.company_name)))
	):
		return company

	if company := _match_buyer_name_or_address(companies, buyer_name, address):
		return company

	if buyer_name and (company := InvoiceEntityResolverMixin().resolve_company(buyer_name, address or "")):
		return company

	if not use_default:
		return None

	from erpnext import get_default_company

	return canonical_company(get_default_company())


def resolve_ocr_buyer_company(analysis: dict) -> str | None:
	"""Find which of our companies an OCR-read invoice is addressed to, or None.

	Never the default company: nothing on the document says it is the buyer.
	"""
	vendor_tax_id = normalize_tax_id(analysis.get("VENDOR_VAT_NUMBER"))
	# TAX_PAYER_ID is the buyer's, but OCR sometimes puts the vendor VAT there
	tax_id = next(
		(
			value
			for value in (analysis.get("RECEIVER_VAT_NUMBER"), analysis.get("TAX_PAYER_ID"))
			if value and normalize_tax_id(value) != vendor_tax_id
		),
		None,
	)

	name, address = analysis.get("RECEIVER_NAME"), analysis.get("RECEIVER_ADDRESS")
	# Textract often leaves the receiver empty and reads the buyer block as NAME/ADDRESS.
	# Those also hold the vendor, so skip them when the vendor is one of our companies.
	if not (name or address) and not is_own_company_name(analysis.get("VENDOR_NAME")):
		name, address = analysis.get("NAME"), analysis.get("ADDRESS")

	return resolve_buyer_company(name, tax_id=tax_id, address=address, use_default=False)


def company_name_key(name: str | None) -> str:
	"""A buyer name reduced to what identifies it: "SARL E.D.C" and "EDC" give "edc"."""
	without_punctuation = re.sub(r"[^\w\s]", "", _fold(strip_legal_forms(_fold(name))))
	return re.sub(r"\s+", " ", without_punctuation).strip()


def _match_buyer_name_or_address(companies: list, name: str | None, address: str | None) -> str | None:
	"""The name and address steps of resolve_buyer_company, most specific first."""
	text = f"{_fold(name)} | {_fold(address)}"
	key = company_name_key(name)

	# The full Company name inside the name or address: "MENUISERIE ELEGANTE\n8 rue…"
	if company := _single(c for c in companies if _contains_words(text, _fold(c.company_name or c.name))):
		return company

	if key and (company := _only(_company_aliases(companies).get(key, ()))):
		return company

	if len(key) > MIN_COMPANY_ALIAS_LENGTH and (company := _closest_company(companies, key)):
		return company

	return _company_at_address(text)


def _company_aliases(companies: list) -> dict[str, set[str]]:
	"""Other names our companies are printed under, by company_name_key."""
	aliases = defaultdict(set)

	def add(alias: str | None, company: str) -> None:
		if len(key := company_name_key(alias)) >= MIN_COMPANY_ALIAS_LENGTH:
			aliases[key].add(company)

	for company in companies:
		add(company.company_name or company.name, company.name)
		add(company.abbr, company.name)

	for address in _company_addresses():
		add(address.address_title, address.company)

	for alias in frappe.get_all("eTransactions Company Name Alias", fields=["receiver_name", "company"]):
		add(alias.receiver_name, alias.company)

	return aliases


def _closest_company(companies: list, key: str) -> str | None:
	"""A misspelled Company name ("Menuiserie Élégnte SAS"), when one Company is clearly closest."""
	scores = sorted(
		(
			(difflib.SequenceMatcher(None, key, company_name_key(c.company_name or c.name)).ratio(), c.name)
			for c in companies
		),
		reverse=True,
	)
	if not scores:
		return None
	best_score, best = scores[0]
	second_score = scores[1][0] if len(scores) > 1 else 0.0
	if best_score >= COMPANY_SIMILARITY and best_score - second_score >= COMPANY_SIMILARITY_GAP:
		return best
	return None


def _company_at_address(text: str) -> str | None:
	"""The Company with an address whose postcode and a street word both appear in ``text``.

	None when the address is shared: two companies may be registered at the same place.
	"""
	digits = set(re.findall(r"\d+", text))
	companies = set()
	for address in _company_addresses():
		postcode = _digits(address.pincode)
		street = _fold(f"{address.address_line1 or ''} {address.address_line2 or ''}")
		words = {
			word
			for word in re.findall(r"[a-z]+", street)
			if len(word) >= 4 and word not in STREET_WORDS and word.upper() not in STOP_WORDS
		}
		if postcode in digits and any(_contains_words(text, word) for word in words):
			companies.add(address.company)
	return _only(companies)


def _company_addresses() -> list:
	address = frappe.qb.DocType("Address")
	link = frappe.qb.DocType("Dynamic Link")
	return (
		frappe.qb.from_(address)
		.join(link)
		.on((link.parent == address.name) & (link.parenttype == "Address"))
		.select(
			address.address_title,
			address.address_line1,
			address.address_line2,
			address.pincode,
			link.link_name.as_("company"),
		)
		.where((link.link_doctype == "Company") & (address.disabled == 0))
		.run(as_dict=True)
	)


def _contains_words(text: str, phrase: str) -> bool:
	return bool(phrase) and re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text) is not None


def _digits(value: str | None) -> str:
	return "".join(c for c in str(value or "") if c.isdigit())


def _fold(value: str | None) -> str:
	"""Compare names the way people read them: no case, no accents, single spaces."""
	decomposed = unicodedata.normalize("NFKD", value or "")
	without_accents = "".join(c for c in decomposed if not unicodedata.combining(c))
	return re.sub(r"\s+", " ", without_accents).strip().casefold()


def _single(companies) -> str | None:
	return _only(c.name for c in companies)


def _only(names) -> str | None:
	names = set(names)
	return names.pop() if len(names) == 1 else None
