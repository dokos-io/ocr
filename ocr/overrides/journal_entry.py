from contextlib import contextmanager

import frappe
from erpnext.accounts.doctype.journal_entry.journal_entry import JournalEntry

RECONCILIATION_FLAG = "ocr_credit_note_reconciliation"

# Voucher types of the entries ERPNext posts on our behalf: the debit note itself
# (PaymentReconciliation.reconcile_dr_cr_note) and the optional exchange gain/loss
# entry (erpnext.accounts.utils.create_gain_loss_journal).
RECONCILIATION_VOUCHER_TYPES = ("Debit Note", "Credit Note", "Exchange Gain Or Loss")

GRANTED_PERMISSIONS = ("create", "write", "submit")


@contextmanager
def system_generated_reconciliation(company, party, source):
	"""Allow the reconciliation entries of a single credit note allocation to be posted.

	Reconciling a supplier credit note against its target invoices is realised by
	ERPNext as a system generated Journal Entry (``reconcile_dr_cr_note``, plus
	``create_gain_loss_journal`` when there is an exchange difference). Both submit
	the entry as the current user, so without this the whole flow would require every
	OCR user to hold create/submit rights on *all* journal entries.

	The document authority is checked on the Pending Purchase Invoice and on the
	Purchase Invoices involved instead; this context manager only lets the resulting
	internal entries through, and only for ``company``/``party``.

	``frappe.flags`` is request and thread scoped, so the grant cannot leak into a
	concurrent request.
	"""
	previous = frappe.flags.get(RECONCILIATION_FLAG)
	frappe.flags[RECONCILIATION_FLAG] = {"company": company, "party": party, "source": source}
	try:
		yield
	finally:
		frappe.flags[RECONCILIATION_FLAG] = previous


class OCRJournalEntry(JournalEntry):
	def has_permission(self, permtype="read", *, debug=False, user=None) -> bool:
		if self._is_ocr_reconciliation_entry(permtype):
			return True

		return super().has_permission(permtype, debug=debug, user=user)

	def _is_ocr_reconciliation_entry(self, permtype) -> bool:
		"""Return True for the entries posted inside ``system_generated_reconciliation``.

		Deliberately a conjunction rather than a bare flag check: the grant must not
		extend to a hand crafted journal entry submitted while a reconciliation happens
		to be in progress.
		"""
		if permtype not in GRANTED_PERMISSIONS:
			return False

		reconciliation = frappe.flags.get(RECONCILIATION_FLAG)
		if not reconciliation:
			return False

		if not self.get("is_system_generated"):
			return False

		if self.get("voucher_type") not in RECONCILIATION_VOUCHER_TYPES:
			return False

		if self.get("company") != reconciliation["company"]:
			return False

		# The gain/loss line carries no party, so only the party lines are checked.
		for account in self.get("accounts") or []:
			if not account.get("party"):
				continue
			if account.get("party_type") != "Supplier" or account.get("party") != reconciliation["party"]:
				return False

		return True
