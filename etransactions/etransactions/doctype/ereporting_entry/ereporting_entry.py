# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from etransactions.components.superpdp.models import (
	B2CPayment,
	B2CPaymentSubtotal,
	B2CTransaction,
	B2CTransactionSubtotal,
)


class eReportingEntry(Document):
	def to_b2c_transaction(self) -> B2CTransaction:
		"""Build the platform payload model for a transaction entry."""
		return B2CTransaction(
			date=str(self.date),
			currency=self.currency or "EUR",
			category_code=self.category_code,
			tax_exclusive_amount=_money(self.tax_exclusive_amount),
			tax_total=_money(self.tax_total),
			role_code=self.role_code,
			tax_due_date_type_code=self.tax_due_date_type_code or None,
			tax_subtotals=[
				B2CTransactionSubtotal(
					tax_percent=_money(s.tax_percent),
					taxable_amount=_money(s.taxable_amount),
					tax_total=_money(s.tax_total),
				)
				for s in self.subtotals
			],
		)

	def to_b2c_payment(self) -> B2CPayment:
		"""Build the platform payload model for a payment entry."""
		return B2CPayment(
			date=str(self.date),
			subtotals=[
				B2CPaymentSubtotal(
					amount=_money(s.amount),
					tax_percent=_money(s.tax_percent),
					category_code=s.category_code or None,
					currency_code=self.currency or None,
				)
				for s in self.subtotals
			],
		)


def _money(value) -> str:
	"""Render a numeric field as the decimal string the platform expects."""
	return str(value if value is not None else 0)
