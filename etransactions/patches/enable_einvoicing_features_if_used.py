import frappe

from etransactions.overrides.master_data import DEFAULT_PROFILE

SETTINGS = "eTransactions Settings"


def execute():
	"""Keep every optional e-invoicing feature a site already uses visible.

	The optional features (Peppol network, public sector, profile choice, advanced
	routing) are off by default and hide their fields. A Single's JSON default does
	not backfill, so this patch turns on, explicitly, each feature for which existing
	data shows it is in use — nothing a site relies on disappears on upgrade.
	"""
	usage = {
		"enable_peppol_network": _uses_peppol(),
		"enable_public_sector": _uses_public_sector(),
		"enable_profile_choice": _uses_profile_choice(),
		"enable_advanced_routing": _uses_advanced_routing(),
	}
	for field, used in usage.items():
		if used:
			frappe.db.set_single_value(SETTINGS, field, 1)


def _uses_peppol() -> bool:
	return _exists("Customer", {"directory_type": "peppol"}) or _exists(
		"Customer", {"etransactions_electronic_address": ["is", "set"]}
	)


def _uses_public_sector() -> bool:
	return (
		_exists("Address", {"etransactions_buyer_reference": ["is", "set"]})
		or _exists("Sales Invoice", {"etransactions_contract_reference": ["is", "set"]})
		or _exists("Sales Order", {"etransactions_contract_reference": ["is", "set"]})
		or _exists("Customer", {"directory_entity_type": "public"})
	)


def _uses_profile_choice() -> bool:
	"""Any profile other than the automatic default is a deliberate choice."""
	default_profile = frappe.db.get_single_value(SETTINGS, "default_etransaction_profile")
	if default_profile and default_profile != DEFAULT_PROFILE:
		return True
	return _exists("Customer", {"etransaction_profile": ["not in", ["", DEFAULT_PROFILE]]}) or _exists(
		"Sales Invoice", {"etransaction_profile": ["not in", ["", DEFAULT_PROFILE]]}
	)


def _uses_advanced_routing() -> bool:
	return (
		_exists("Customer", {"directory_pinned": 1})
		or _exists("Customer", {"accredited_platform_override": ["is", "set"]})
		or _exists("Customer Group", {"accredited_platform_override": ["is", "set"]})
	)


def _exists(doctype: str, filters: dict) -> bool:
	"""``frappe.db.exists`` that tolerates a custom field not created yet."""
	if not all(frappe.db.has_column(doctype, field) for field in filters):
		return False
	return bool(frappe.db.exists(doctype, filters))
