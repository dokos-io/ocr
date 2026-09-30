"""Optional e-invoicing features, off by default.

The default e-invoicing experience covers what most users need: Factur-X invoices
sent to French B2B customers, routed through the French directory. Anything beyond
that is opt-in through a toggle in eTransactions Settings; while a toggle is off, the
related fields stay hidden and the matching behaviour falls back to the default flow.
"""

import frappe

# Feature key -> eTransactions Settings check field.
FEATURES = {
	"peppol": "enable_peppol_network",
	"public_sector": "enable_public_sector",
	"profile_choice": "enable_profile_choice",
	"advanced_routing": "enable_advanced_routing",
}


def is_feature_enabled(feature: str) -> bool:
	"""Whether an optional e-invoicing feature is on (always off while e-invoicing is)."""
	return bool(get_enabled_features().get(feature))


def get_enabled_features() -> dict[str, int]:
	"""All optional features as ``{feature: 0|1}``, as exposed to the client in boot."""
	settings = frappe.get_cached_doc("eTransactions Settings")
	enabled = bool(settings.get("enable_einvoicing"))
	return {key: int(enabled and bool(settings.get(field))) for key, field in FEATURES.items()}
