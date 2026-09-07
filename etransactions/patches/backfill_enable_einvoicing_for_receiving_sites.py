import frappe


def execute():
	"""Turn `enable_einvoicing` back on for sites that were already receiving.

	`poll_incoming_flows` is gated on `is_receiving_enabled()`, i.e. on
	`enable_einvoicing` *and* `enable_receiving_einvoices`. That gate was added after
	`enable_einvoicing` shipped, and only the new field got a backfill — so a site whose
	`enable_einvoicing` had stayed at its JSON default of 0 kept receiving invoices until
	the gate landed, then stopped dead, silently.

	`set_default_enable_einvoicing` cannot repair those sites: it is already recorded in
	Patch Log and never runs twice. It also missed them in the first place, because it
	looks for an active platform or a default profile and a site created from scratch runs
	its patches before either exists.

	The condition here is deliberately narrower than "an active platform exists", which is
	the stale-record case the gate was written to block. `last_incoming_poll` is only ever
	written after a successful listing, so it is positive evidence that this site really
	was receiving before the gate — not that someone left a platform row switched on.
	"""
	if frappe.get_single_value("eTransactions Settings", "enable_einvoicing"):
		return

	was_receiving = frappe.db.exists(
		"eTransactions Accredited Platform",
		{
			"is_active": 1,
			"transaction_type": ["in", ["Purchases", "Both"]],
			"last_incoming_poll": ["is", "set"],
		},
	)
	if not was_receiving:
		return

	frappe.db.set_single_value("eTransactions Settings", "enable_einvoicing", 1)
