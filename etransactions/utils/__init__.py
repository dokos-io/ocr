from base64 import b64encode
import re
import datetime
from dateutil.parser import parse
from babel.dates import parse_date

import frappe
from frappe.utils import time_diff, getdate

from enum import Enum
from functools import total_ordering

DateTimeLikeObject = str | datetime.date | datetime.datetime

def parse_number(text):
	# Borrowed from https://github.com/hayj/SystemTools/blob/master/systemtools/number.py
	"""
		Return the first number in the given text for any locale.
		TODO we actually don't take into account spaces for only
		3-digited numbers (like "1 000") so, for now, "1 0" is 10.
		TODO parse cases like "125,000.1,0.2" (125000.1).

		:example:
		>>> parseNumber("a 125,00 €")
		125
		>>> parseNumber("100.000,000")
		100000
		>>> parseNumber("100 000,000")
		100000
		>>> parseNumber("100,000,000")
		100000000
		>>> parseNumber("100 000 000")
		100000000
		>>> parseNumber("100.001 001")
		100.001
		>>> parseNumber("$.3")
		0.3
		>>> parseNumber(".003")
		0.003
		>>> parseNumber(".003 55")
		0.003
		>>> parseNumber("3 005")
		3005
		>>> parseNumber("1.190,00 €")
		1190
		>>> parseNumber("1190,00 €")
		1190
		>>> parseNumber("1,190.00 €")
		1190
		>>> parseNumber("$1190.00")
		1190
		>>> parseNumber("$1 190.99")
		1190.99
		>>> parseNumber("$-1 190.99")
		-1190.99
		>>> parseNumber("1 000 000.3")
		1000000.3
		>>> parseNumber('-151.744122')
		-151.744122
		>>> parseNumber('-1')
		-1
		>>> parseNumber("1 0002,1.2")
		10002.1
		>>> parseNumber("")

		>>> parseNumber(None)

		>>> parseNumber(1)
		1
		>>> parseNumber(1.1)
		1.1
		>>> parseNumber("rrr1,.2o")
		1
		>>> parseNumber("rrr1rrr")
		1
		>>> parseNumber("rrr ,.o")

	"""
	try:
		# First we return None if we don't have something in the text:
		if text is None:
			return None
		if isinstance(text, int) or isinstance(text, float):
			return text
		text = text.strip()
		if text == "":
			return None
		# Next we get the first "[0-9,. ]+":
		n = re.search("-?[0-9]*([,. ]?[0-9]+)+", text).group(0)
		n = n.strip()
		if not re.match(".*[0-9]+.*", text):
			return None
		# Then we cut to keep only 2 symbols:
		while " " in n and "," in n and "." in n:
			index = max(n.rfind(','), n.rfind(' '), n.rfind('.'))
			n = n[0:index]
		n = n.strip()
		# We count the number of symbols:
		symbolsCount = 0
		for current in [" ", ",", "."]:
			if current in n:
				symbolsCount += 1
		# If we don't have any symbol, we do nothing:
		if symbolsCount == 0:
			pass
		# With one symbol:
		elif symbolsCount == 1:
			# If this is a space, we just remove all:
			if " " in n:
				n = n.replace(" ", "")
			# Else we set it as a "." if one occurence, or remove it:
			else:
				theSymbol = "," if "," in n else "."
				if n.count(theSymbol) > 1:
					n = n.replace(theSymbol, "")
				else:
					n = n.replace(theSymbol, ".")
		else:
			# Now replace symbols so the right symbol is "." and all left are "":
			rightSymbolIndex = max(n.rfind(','), n.rfind(' '), n.rfind('.'))
			rightSymbol = n[rightSymbolIndex:rightSymbolIndex+1]
			if rightSymbol == " ":
				return parse_number(n.replace(" ", "_"))
			n = n.replace(rightSymbol, "R")
			leftSymbolIndex = max(n.rfind(','), n.rfind(' '), n.rfind('.'))
			leftSymbol = n[leftSymbolIndex:leftSymbolIndex+1]
			n = n.replace(leftSymbol, "L")
			n = n.replace("L", "")
			n = n.replace("R", ".")
		# And we cast the text to float or int:
		n = float(n)
		if n.is_integer():
			return int(n)
		else:
			return n
	except Exception:
		pass
	return None



# Don't use Dokos standard function for compatibility with Frappe
def time_diff_in_minutes(
	string_ed_date: DateTimeLikeObject, string_st_date: DateTimeLikeObject
) -> float:
	"""Returns the difference between given two dates in minutes."""
	return round(float(time_diff(string_ed_date, string_st_date).total_seconds()) / 60, 2)



def date_parser(date, locale=None) -> datetime.date:
	if not locale:
		default_country = frappe.db.get_single_value("System Settings", "country")
		locale = frappe.get_cached_value("Country", default_country)

	try:
		return parse_date(date, locale=locale)
	except Exception:
		pass

	try:
		return getdate(parse(date))
	except Exception:
		return getdate()


def as_base_64(content: str | bytes) -> str:
	"""Convert a string or bytes object to a base64-encoded string."""
	if isinstance(content, str):
		content = content.encode("utf-8")

	return b64encode(content).decode("utf-8")


@total_ordering
class EInvoiceProfile(Enum):
	"""
	Profiles according to Factur-X Specification 1.07.2 page 18.
	"""

	MINIMUM = "MINIMUM"
	BASIC_WL = "BASIC WL"
	BASIC = "BASIC"
	EN16931 = "EN16931"
	EXTENDED = "EXTENDED"
	XRECHNUNG = "FACTUR-X"
	# French CTC profile (Extended CIUS with the cpro.gouv.fr guideline), required
	# for the French e-invoicing reform / B2G flows. Extended-based.
	CTC_FR = "EXTENDED CTC-FR"

	def __lt__(self, other):
		# https://stackoverflow.com/a/39269589
		order = [
			EInvoiceProfile.MINIMUM,
			EInvoiceProfile.BASIC_WL,
			EInvoiceProfile.BASIC,
			EInvoiceProfile.EN16931,
			EInvoiceProfile.XRECHNUNG,
			EInvoiceProfile.EXTENDED,
			EInvoiceProfile.CTC_FR,
		]
		return order.index(self) < order.index(other)


# Map of EInvoiceProfile to drafthorse schema name
PROFILE_TO_SCHEMA = {
	EInvoiceProfile.MINIMUM: "FACTUR-X_MINIMUM",
	EInvoiceProfile.BASIC_WL: "FACTUR-X_BASICWL",
	EInvoiceProfile.BASIC: "FACTUR-X_BASIC",
	EInvoiceProfile.EN16931: "FACTUR-X_EN16931",
	EInvoiceProfile.XRECHNUNG: "FACTUR-X_EN16931",
	EInvoiceProfile.EXTENDED: "FACTUR-X_EXTENDED",
	EInvoiceProfile.CTC_FR: "FACTUR-X_EXTENDED",
}

# Map of EInvoiceProfile to GuidelineSpecifiedDocumentContextParameter
PROFILE_TO_GUIDELINE = {
	EInvoiceProfile.MINIMUM: "urn:factur-x.eu:1p0:minimum",
	EInvoiceProfile.BASIC_WL: "urn:factur-x.eu:1p0:basicwl",
	EInvoiceProfile.BASIC: "urn:cen.eu:en16931:2017#compliant#urn:factur-x.eu:1p0:basic",
	EInvoiceProfile.EN16931: "urn:cen.eu:en16931:2017",
	EInvoiceProfile.XRECHNUNG: "urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0",
	EInvoiceProfile.EXTENDED: "urn:cen.eu:en16931:2017#conformant#urn:factur-x.eu:1p0:extended",
	EInvoiceProfile.CTC_FR: "urn.cpro.gouv.fr:1p0:extended-ctc-fr",
}
GUIDELINE_TO_PROFILE = {v: k for k, v in PROFILE_TO_GUIDELINE.items()}


def get_drafthorse_schema(profile: EInvoiceProfile) -> str:
	"""Return the drafthorse schema name for the given profile."""
	return PROFILE_TO_SCHEMA.get(profile)


def get_guideline(profile: EInvoiceProfile) -> str:
	"""Return the guideline for the given profile."""
	return PROFILE_TO_GUIDELINE.get(profile)


def get_profile(guideline: str) -> EInvoiceProfile:
	"""Return the profile for the given guideline."""
	return GUIDELINE_TO_PROFILE.get(guideline)


def identity(value):
	"""Used for dummy translation"""
	return value