import frappe

from etransactions.controllers.entity_resolver import (
	is_learnable_vendor_name,
	normalize_vendor_name,
)


def execute():
	"""Drop the vendor-name aliases the learning loop should never have stored.

	Until now `_learn_from_manual_match` recorded whatever OCR put in VENDOR_NAME as soon as
	a user changed the supplier, with no check on what that string was. Textract routinely
	returns the buyer's letterhead there, so sites accumulated rows mapping their own company
	name onto whichever supplier was being corrected — several suppliers per name. Resolution
	then read one of them arbitrarily, at "high" confidence, and misrouted every later invoice
	whose vendor name OCR'd the same way.

	Two classes of row go: names that identify no supplier (our own company, fragments) and
	names claimed by more than one supplier. Ambiguous rows are dropped rather than arbitrated
	— the correct owner is not recoverable here, and a wrong survivor keeps misrouting.
	Suppliers stay untouched; only the learned shortcut is cleared, so matching falls back to
	tax id, IBAN and name similarity and relearns from the next confirmed correction.
	"""
	aliases = frappe.get_all(
		"eTransactions Supplier Name Alias", fields=["name", "supplier", "vendor_name"]
	)
	if not aliases:
		return

	claimants_by_name = {}
	for alias in aliases:
		normalized = normalize_vendor_name(alias.vendor_name)
		claimants_by_name.setdefault(normalized, set()).add(alias.supplier)

	dropped = 0
	for alias in aliases:
		normalized = normalize_vendor_name(alias.vendor_name)

		if not is_learnable_vendor_name(normalized) or len(claimants_by_name[normalized]) > 1:
			frappe.delete_doc(
				"eTransactions Supplier Name Alias", alias.name, force=True, ignore_permissions=True
			)
			dropped += 1
			continue

		if normalized != alias.vendor_name:
			# Collapse the PDF line breaks OCR carried in, so the same vendor stops arriving
			# under two spellings.
			frappe.db.set_value(
				"eTransactions Supplier Name Alias", alias.name, "vendor_name", normalized,
				update_modified=False,
			)

	if dropped:
		print(f"Dropped {dropped} unusable supplier name alias(es) of {len(aliases)}.")
