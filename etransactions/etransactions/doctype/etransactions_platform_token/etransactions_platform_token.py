# Copyright (c) 2026, Dokos SAS and contributors
# For license information, please see license.txt

from frappe.model.document import Document


class eTransactionsPlatformToken(Document):
	"""OAuth tokens for an accredited platform, kept off the platform record.

	The authorization_code flow rotates the access (and sometimes refresh) token
	on every refresh. Storing them on their own row — rather than on the platform
	doc, which is read on every send — avoids "could not serialize access due to
	concurrent update" contention (the reason akretion uses a dedicated table).
	"""

	# begin: auto-generated types
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		access_token: DF.Password | None
		expires_at: DF.Datetime | None
		platform: DF.Link
		refresh_token: DF.Password | None
	# end: auto-generated types
	pass
