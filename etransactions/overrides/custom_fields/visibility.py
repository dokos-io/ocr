"""``depends_on`` expressions for the e-invoicing custom fields.

Every e-invoicing field is hidden while e-invoicing is off
(``frappe.boot.einvoicing_enabled``). Fields that belong to an optional feature
(see etransactions.features) are also hidden until that feature is enabled in
eTransactions Settings.
"""

ENABLED = "frappe.boot.einvoicing_enabled"


def einvoicing() -> str:
	return f"eval:{ENABLED}"


def feature(key: str, *or_conditions: str) -> str:
	"""Visible when e-invoicing and the ``key`` feature are on, or any ``or_conditions`` holds.

	Pass e.g. ``"doc.some_field"`` so a field that already carries a value stays
	visible (and editable) after its feature is turned off.
	"""
	condition = f"(frappe.boot.einvoicing_features || {{}}).{key}"
	if or_conditions:
		condition = " || ".join((condition, *or_conditions))
	return f"eval:{ENABLED} && ({condition})"
