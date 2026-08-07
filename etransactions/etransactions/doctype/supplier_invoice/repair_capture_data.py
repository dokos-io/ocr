"""One-off remediation for a site whose invoice capture ran on the old code.

The code fixes stop new damage; this repairs what is already stored. It reports by default
and only writes when called with ``apply=True``, because every action here is a judgement
about accounting data:

    bench --site <site> execute etransactions.etransactions.doctype.supplier_invoice.repair_capture_data.run
    bench --site <site> execute etransactions.etransactions.doctype.supplier_invoice.repair_capture_data.run --kwargs "{'apply': True}"

The alias table itself is cleaned by `etransactions.patches.clean_supplier_name_aliases`,
which runs on migrate. What is left needs a human to look at the dry run first:

1. person names and address fragments learned as vendor aliases — indistinguishable in code
   from a legitimate sole trader, so they are listed, not deleted;
2. supplier item aliases backfilled from purchase history, so prefill works on day one
   instead of after a month of learning;
3. invoices still unmatched or matched with low confidence, re-resolved through the fixed
   resolver — reported, never saved, since a wrong supplier is worse than none;
4. submitted purchase invoices posted on their creation day instead of their supplier
   invoice's date — reported only. Correcting a submitted GL document is an accounting
   decision, not a script's.
"""

from collections import Counter, defaultdict

import frappe
from frappe.utils import getdate

from etransactions.controllers.entity_resolver import LEGAL_FORMS, InvoiceEntityResolverMixin

# A vendor name that is mostly capitalised given-name/surname words and nothing else is
# usually the traveller, the guest or the signatory, not the seller. Matched on whole words:
# as substrings these swallow "défendre" and "Commerce".
PERSON_TITLES = frozenset({"madame", "monsieur", "mme", "mlle", "mr", "m", "dr"})
# Below this share, the supplier's history is too scattered for one line to be a safe guess.
DOMINANT_ITEM_SHARE = 0.6


def run(apply: bool = False) -> dict:
	report = {
		"suspect_name_aliases": report_suspect_name_aliases(),
		"item_aliases_backfilled": backfill_supplier_item_aliases(apply),
		"resolvable_invoices": report_resolvable_invoices(),
		"misposted_purchase_invoices": report_misposted_purchase_invoices(),
	}

	if apply:
		frappe.db.commit()  # nosemgrep
	else:
		frappe.db.rollback()
		print("\nDry run — nothing was written. Re-run with apply=True to keep the backfill.")

	return report


def report_suspect_name_aliases() -> list[dict]:
	"""Vendor aliases that read as a person rather than a company.

	Left for review: "Lorris Meric" and "Charles-Henri Decultot" are real suppliers on this
	site, so no rule can separate a mislearned passenger name from a genuine sole trader.
	"""
	suspects = []
	for alias in frappe.get_all(
		"eTransactions Supplier Name Alias", fields=["name", "supplier", "vendor_name"]
	):
		vendor_name = alias.vendor_name or ""
		words = vendor_name.split()
		titled = {w.strip(".").lower() for w in words} & PERSON_TITLES
		# Two or three shouted words with no digits and no legal form: a person's name shape.
		bare_name = (
			1 < len(words) <= 3
			and not any(c.isdigit() for c in vendor_name)
			and vendor_name.upper() == vendor_name
			and not {w.upper() for w in words} & LEGAL_FORMS
		)
		if titled or bare_name:
			suspects.append(
				{"alias": alias.name, "supplier": alias.supplier, "vendor_name": vendor_name}
			)

	print(f"\n{len(suspects)} vendor alias(es) look like a person's name — review and delete by hand:")
	for suspect in suspects:
		print(f"  {suspect['vendor_name']!r} -> {suspect['supplier']}  ({suspect['alias']})")

	return suspects


def backfill_supplier_item_aliases(apply: bool) -> list[dict]:
	"""Seed the supplier item mapping from how each supplier has actually been booked.

	Only suppliers who consistently book to the same item are seeded: a scattered history is
	not a rule, and a wrong prefill costs more than an empty one.
	"""
	lines = frappe.db.sql(
		"""
		SELECT pi.supplier, pii.item_code, pii.expense_account, pii.cost_center, pii.item_tax_template
		FROM `tabPurchase Invoice Item` pii
		JOIN `tabPurchase Invoice` pi ON pi.name = pii.parent
		WHERE pi.docstatus = 1 AND pi.is_return = 0 AND pii.item_code IS NOT NULL
		""",
		as_dict=True,
	)

	by_supplier = defaultdict(Counter)
	details = {}
	for line in lines:
		key = (line.item_code, line.expense_account, line.cost_center, line.item_tax_template)
		by_supplier[line.supplier][key] += 1
		details[key] = line

	created = []
	for supplier, combinations in by_supplier.items():
		total = sum(combinations.values())
		(top_key, top_count), = combinations.most_common(1)
		if top_count / total < DOMINANT_ITEM_SHARE:
			continue

		line = details[top_key]
		# Keyed on the item's own name: the historical rows carry no supplier line label, so
		# this seeds the fallback rather than per-line recognition.
		label = frappe.db.get_value("Item", line.item_code, "item_name") or line.item_code
		if frappe.db.exists(
			"eTransactions Supplier Item Alias", {"supplier": supplier, "item_code": line.item_code}
		):
			continue

		created.append({
			"supplier": supplier,
			"label": label,
			"item_code": line.item_code,
			"expense_account": line.expense_account,
			"share": round(top_count / total * 100),
		})

		if apply:
			alias = frappe.new_doc("eTransactions Supplier Item Alias")
			alias.supplier = supplier
			alias.supplier_item_code = label
			alias.item_code = line.item_code
			alias.expense_account = line.expense_account
			alias.cost_center = line.cost_center
			alias.item_tax_template = line.item_tax_template
			alias.insert(ignore_permissions=True)

	print(f"\n{len(created)} supplier item mapping(s) from purchase history:")
	for row in sorted(created, key=lambda r: -r["share"])[:20]:
		print(f"  {row['supplier'][:36]:38s} {row['item_code'][:28]:30s} {row['share']:3d}% of lines")

	return created


def report_resolvable_invoices() -> list[dict]:
	"""Invoices the fixed resolver would now match, or would match differently."""
	resolver = InvoiceEntityResolverMixin()
	changes = []

	for invoice in frappe.get_all(
		"Supplier Invoice",
		filters={"status": ("not in", ("Completed", "Closed"))},
		fields=["name", "supplier", "match_confidence", "tax_id", "vendor_iban", "ocr_request"],
	):
		vendor_name = None
		if invoice.ocr_request:
			raw = frappe.db.get_value("OCR Request", invoice.ocr_request, "analysis")
			vendor_name = (frappe.parse_json(raw) or {}).get("VENDOR_NAME") if raw else None

		resolved = resolver.resolve_supplier(
			seller_name=vendor_name, tax_id=invoice.tax_id, iban=invoice.vendor_iban
		)
		if resolved and resolved != invoice.supplier:
			changes.append({
				"invoice": invoice.name,
				"vendor_name": vendor_name,
				"was": invoice.supplier,
				"now": resolved,
				"confidence": resolver._match_confidence,
			})

	print(f"\n{len(changes)} open invoice(s) would resolve to a different supplier:")
	for change in changes:
		print(
			f"  {change['invoice']}: {change['was'] or '(none)'} -> {change['now']}"
			f"  [{change['confidence']}]  vendor {change['vendor_name']!r}"
		)

	return changes


def report_misposted_purchase_invoices() -> list[dict]:
	"""Submitted invoices posted on their creation day instead of the captured date.

	These are the ones the `after_mapping` fix prevents from here on. Repointing them means
	reversing and reissuing GL entries, possibly across a closed period — reported so the
	accountant can decide, never touched.
	"""
	misposted = []
	for row in frappe.db.sql(
		"""
		SELECT pi.name, pi.posting_date, pi.creation, si.posting_date AS captured_date, pi.supplier
		FROM `tabPurchase Invoice` pi
		JOIN `tabSupplier Invoice` si ON si.name = pi.supplier_invoice
		WHERE pi.docstatus = 1
		  AND pi.set_posting_time = 0
		  AND pi.posting_date != si.posting_date
		  AND pi.posting_date = DATE(pi.creation)
		ORDER BY pi.posting_date DESC
		""",
		as_dict=True,
	):
		misposted.append({
			"purchase_invoice": row.name,
			"supplier": row.supplier,
			"posted": str(row.posting_date),
			"captured": str(row.captured_date),
			"wrong_period": getdate(row.posting_date).strftime("%Y-%m")
			!= getdate(row.captured_date).strftime("%Y-%m"),
		})

	wrong_period = sum(1 for m in misposted if m["wrong_period"])
	print(
		f"\n{len(misposted)} submitted purchase invoice(s) were posted on their creation day"
		f" ({wrong_period} of them in the wrong month) — accounting decision, not touched:"
	)
	for row in misposted[:20]:
		flag = "  <- wrong month" if row["wrong_period"] else ""
		print(f"  {row['purchase_invoice']}: posted {row['posted']}, captured {row['captured']}{flag}")

	return misposted
