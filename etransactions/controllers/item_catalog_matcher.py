import unicodedata

import frappe

from etransactions.etransactions.doctype.etransactions_supplier_item_alias.etransactions_supplier_item_alias import (
	normalize_supplier_item_code,
)

# Below this many characters a token is usually a stopword ("de", "the", "for") rather than
# something that identifies what was bought.
MIN_TOKEN_LENGTH = 4
# Share of the shorter token set that must overlap for a catalog guess to be worth surfacing.
MIN_OVERLAP = 0.5
# The best candidate must clear the runner-up by this much, or the guess is too ambiguous to trust.
MIN_GAP = 0.1


def _tokenize(label: str | None) -> set[str]:
	"""Words a vendor's line label and an Item's name can plausibly share.

	Amounts, currencies and punctuation are already gone via `normalize_supplier_item_code`.
	What is left still needs accents folded (a French Item name and an unaccented OCR/XML
	label must compare equal) and short filler words dropped, or "de"/"for"/"1" would inflate
	the overlap between two otherwise unrelated lines. A trailing "s" is stripped too, so
	"service" and "services" count as the same token instead of missing each other.
	"""
	normalized = normalize_supplier_item_code(label)
	folded = unicodedata.normalize("NFKD", normalized).encode("ascii", "ignore").decode("ascii")

	tokens = set()
	for word in folded.split():
		if len(word) < MIN_TOKEN_LENGTH:
			continue
		tokens.add(word[:-1] if word.endswith("s") and len(word) > MIN_TOKEN_LENGTH else word)

	return tokens


def get_item_catalog() -> list[frappe._dict]:
	"""Enabled Items, fetched once per invoice rather than once per line."""
	return frappe.get_all("Item", filters={"disabled": 0}, fields=["item_code", "item_name"])


def match_item_from_catalog(label: str | None, catalog: list[frappe._dict]) -> str | None:
	"""Best-effort guess of which existing Item a vendor's line label refers to.

	Used only once the supplier-specific alias lookup has come up empty (typically the first
	invoice ever received from that supplier): rather than leave `item_code` blank, suggest
	whichever catalog Item's name shares the most words with the label. This is plain text
	overlap, not domain knowledge — it will not connect "Amazon Route 53" to "Services Cloud" —
	so it only ever returns a match backed by an actual shared word, and stays silent rather
	than guess when two candidates are too close to call.
	"""
	label_tokens = _tokenize(label)
	if not label_tokens:
		return None

	scores = []
	for item in catalog:
		item_tokens = _tokenize(item.item_name)
		if not item_tokens:
			continue
		overlap = len(label_tokens & item_tokens) / min(len(label_tokens), len(item_tokens))
		if overlap >= MIN_OVERLAP:
			scores.append((item.item_code, overlap))

	if not scores:
		return None

	scores.sort(key=lambda pair: pair[1], reverse=True)
	best_code, best_score = scores[0]
	second_score = scores[1][1] if len(scores) > 1 else 0.0
	if (best_score - second_score) < MIN_GAP:
		return None

	return best_code
