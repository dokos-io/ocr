# Copyright (c) 2026, Dokos SAS and Contributors
# License: GNU General Public License v3. See license.txt

"""Sales Order e-invoicing integration.

Determining the accredited-platform routing at order time (rather than only on
the invoice) lets the routing be validated when the order is *confirmed* — when
the commitment reference is still easy to obtain — and propagated to the invoice
so the establishment is known before the e-invoice is built. Mirrors akretion's
``l10n_fr_einvoicing_sale``.
"""

import frappe
from frappe import _

from etransactions.plateforme_agreee.classification import EINVOICED, classify_transaction


def on_validate(doc, method=None):
	"""Resolve the routing line for the order's establishment (e-invoiced buyers).

	Pure determination — no platform calls. Respects a manually chosen line and
	clears the line for buyers that are e-reported / out of scope.
	"""
	if not doc.get("customer"):
		return

	from etransactions.plateforme_agreee.session import get_platform_settings

	if not get_platform_settings(doc.company):
		return

	cls = classify_transaction(doc.company, "Customer", doc.customer, doc.get("customer_address"))
	if cls not in EINVOICED:
		# B2C / B2Bi / out of scope: e-reported, no structured routing line.
		if doc.get("etransactions_routing_line"):
			doc.etransactions_routing_line = None
		return

	# Keep a line the user picked manually.
	if doc.get("etransactions_routing_line"):
		return

	from etransactions.plateforme_agreee.routing import resolve_routing

	line = resolve_routing("Customer", doc.customer, doc.get("customer_address"))
	if line:
		doc.etransactions_routing_line = line


def before_submit(doc, method=None):
	"""Confirmation-time directory sync, then enforce the commitment reference.

	Syncs the buyer's directory (honouring ``directory_sync_on_submit``), re-runs
	the routing determination against the freshly synced lines, and blocks
	confirmation when the chosen line requires a commitment reference (Customer's
	Purchase Order No) that is missing.
	"""
	if not doc.get("customer"):
		return

	from etransactions.plateforme_agreee.directory import maybe_sync_on_confirm

	maybe_sync_on_confirm(doc.company, doc.customer, origin=f"Sales Order {doc.name}")

	# Re-resolve against the (possibly updated) directory lines.
	on_validate(doc, method)

	line = doc.get("etransactions_routing_line")
	if (
		line
		and frappe.db.get_value("eInvoicing Directory Line", line, "commitment_required")
		and not doc.get("po_no")
	):
		frappe.throw(
			_(
				"The selected accredited-platform routing line requires a commitment reference. "
				"Set the Customer's Purchase Order No (commande/marché) before confirming this order."
			)
		)
