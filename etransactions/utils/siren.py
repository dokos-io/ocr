"""French SIREN validation helpers.

A SIREN is a 9-digit business identifier, valid only if it passes the Luhn
checksum. A French VAT number (``FR`` + 2 key chars + 9 digits) embeds the SIREN
as its trailing 9 digits, so the two can be cross-checked. Pure-Python and
dependency-free, mirror of :mod:`etransactions.utils.vat`.
"""

import re


def _luhn_ok(digits: str) -> bool:
	"""Return whether an all-digit string passes the Luhn checksum."""
	total = 0
	# Double every second digit starting from the right.
	for index, char in enumerate(reversed(digits)):
		value = int(char)
		if index % 2 == 1:
			value *= 2
			if value > 9:
				value -= 9
		total += value
	return total % 10 == 0


def is_valid_siren(siren: str | None) -> bool:
	"""Return whether ``siren`` is exactly 9 digits passing the Luhn checksum."""
	if not siren:
		return False
	siren = siren.replace(" ", "")
	return bool(re.fullmatch(r"\d{9}", siren)) and _luhn_ok(siren)


def siren_from_vat(vat_id: str | None) -> str | None:
	"""Return the 9-digit SIREN embedded in a French VAT number, else ``None``.

	A French VAT number is ``FR`` + a 2-char key + the 9-digit SIREN.
	"""
	if not vat_id:
		return None
	vat_id = vat_id.replace(" ", "").upper()
	if not vat_id.startswith("FR"):
		return None
	match = re.fullmatch(r"FR[0-9A-Z]{2}(\d{9})", vat_id)
	return match.group(1) if match else None


def vat_matches_siren(vat_id: str | None, siren: str | None) -> bool:
	"""Return whether a VAT number is consistent with a SIREN.

	``True`` when there is nothing to contradict (no SIREN, or a non-French /
	unparsable VAT), or when the VAT's embedded SIREN equals ``siren``.
	"""
	if not siren:
		return True
	embedded = siren_from_vat(vat_id)
	if embedded is None:
		return True
	return embedded == siren.replace(" ", "")
