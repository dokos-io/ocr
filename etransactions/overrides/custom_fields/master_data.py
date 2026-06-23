from erpnext.setup.utils import identity as _


customer_fields = [
	{
		"fieldname": "siren_number",
		"label": _("SIREN Number"),
		"fieldtype": "Data",
		"insert_after": "tax_id",
		"length": 9,
	},
	{
		"fieldname": "etransactions_tab",
		"fieldtype": "Tab Break",
		"label": _("eTransactions"),
		"insert_after": "selling_party_html",
	},
	# Readiness indicator (hero): a status pill + fixable checklist, a one-line
	# routing summary and the single primary action (Sync directory), rendered by
	# einvoice_readiness_indicator.js. The fields below are edited natively.
	{
		"fieldname": "etransactions_wizard_html",
		"fieldtype": "HTML",
		"insert_after": "etransactions_tab",
	},
	# --- Identity: the few fields a user actually sets ---
	{
		"fieldname": "pa_identity_section",
		"label": _("Identity"),
		"fieldtype": "Section Break",
		"insert_after": "etransactions_wizard_html",
	},
	{
		"fieldname": "etransaction_profile",
		"label": "eTransaction Profile",
		"fieldtype": "Link",
		"options": "eTransaction Profile",
		"insert_after": "pa_identity_section",
	},
	{
		"fieldname": "etransactions_buyer_reference",
		"label": _("Buyer Reference"),
		"insert_after": "etransaction_profile",
		"fieldtype": "Data",
	},
	{
		"fieldname": "etransactions_contract_reference",
		"label": _("Contract Reference"),
		"description": _("Default public-procurement contract number (numéro de marché) for B2G invoices."),
		"insert_after": "etransactions_buyer_reference",
		"fieldtype": "Data",
	},
	# --- Routing: discovered and maintained automatically by directory sync ---
	{
		"fieldname": "pa_directory_section",
		"label": _("Routing — managed automatically"),
		"fieldtype": "Section Break",
		"insert_after": "etransactions_contract_reference",
		"collapsible": 1,
	},
	# Read-only establishments + routing-line table (customer.js via
	# get_party_establishments) — the visual status, shown first in the section.
	{
		"fieldname": "pa_establishments_html",
		"fieldtype": "HTML",
		"insert_after": "pa_directory_section",
	},
	{
		"fieldname": "directory_entity_type",
		"label": _("Directory Entity Type"),
		"fieldtype": "Select",
		"options": "\nprivate\npublic\nno",
		"insert_after": "pa_establishments_html",
		"read_only": 1,
		"in_list_view": 0,
	},
	{
		"fieldname": "directory_name",
		"label": _("Name in Directory"),
		"fieldtype": "Data",
		"insert_after": "directory_entity_type",
		"read_only": 1,
	},
	{
		"fieldname": "directory_closed",
		"label": _("Entity Closed in Directory"),
		"fieldtype": "Check",
		"insert_after": "directory_name",
		"read_only": 1,
	},
	{
		"fieldname": "pa_directory_col_break",
		"fieldtype": "Column Break",
		"insert_after": "directory_closed",
	},
	{
		"fieldname": "directory_update_date",
		"label": _("Directory Last Updated"),
		"fieldtype": "Date",
		"insert_after": "pa_directory_col_break",
		"read_only": 1,
	},
	{
		"fieldname": "default_directory_line",
		"label": _("Default Directory Line"),
		"fieldtype": "Link",
		"options": "eInvoicing Directory Line",
		"insert_after": "directory_update_date",
		"description": _("Default routing line used when no establishment-specific line matches the invoice address."),
	},
	{
		"fieldname": "directory_type",
		"label": _("Directory"),
		"fieldtype": "Select",
		# Stored values match the SuperPDP API contract ("peppol" | "ppf");
		# "ppf" is the French national directory (Portail Public de Facturation).
		"options": "\npeppol\nppf",
		"default": "ppf",
		"insert_after": "default_directory_line",
		"description": _("Which directory to look in when syncing routing lines: Peppol or the French national directory (PPF)."),
	},
	{
		"fieldname": "directory_pinned",
		"label": _("Directory Pinned"),
		"fieldtype": "Check",
		"insert_after": "directory_type",
		"description": _(
			"Skip automatic directory sync; routing is maintained manually "
			"(e.g. the SuperPDP sandbox recipient). Unpin to let sync update the lines."
		),
	},
	{
		"fieldname": "accredited_platform_override",
		"label": _("eTransactions Accredited Platform Override"),
		"fieldtype": "Link",
		"options": "eTransactions Accredited Platform",
		"insert_after": "directory_pinned",
		"description": _("Override the default eTransactions Accredited Platform for this customer"),
	},
	# Manual electronic address (BT-49) — fallback only, when the party is not in
	# the directory. Normally the synced routing line is authoritative.
	{
		"fieldname": "etransactions_electronic_address_scheme",
		"label": _("Electronic Address Scheme"),
		"insert_after": "accredited_platform_override",
		"fieldtype": "Link",
		"options": "Common Code",
	},
	{
		"fieldname": "etransactions_electronic_address",
		"label": _("Electronic Address"),
		"insert_after": "etransactions_electronic_address_scheme",
		"fieldtype": "Data",
		"depends_on": "etransactions_electronic_address_scheme",
	},
]

company_fields = [
		# NB: Company.siren_number is a standard ERPNext field (company.json),
		# so it is not (re)declared here — only read by the CDAR/generator code.
		{
			"fieldname": "etransactions_tab",
			"fieldtype": "Tab Break",
			"label": _("eTransactions"),
			"insert_after": "connections_tab"
		},
		{
			"fieldname": "etransactions_electronic_address_scheme",
			"label": _("Electronic Address Scheme"),
			"insert_after": "etransactions_tab",
			"fieldtype": "Link",
			"options": "Common Code",
		},
		{
			"fieldname": "etransactions_electronic_address",
			"label": _("Electronic Address"),
			"insert_after": "etransactions_electronic_address_scheme",
			"fieldtype": "Data",
			"depends_on": "etransactions_electronic_address_scheme",
		},
		{
			# Drives the PPF e-reporting declaration schedule. Pushed to the
			# platform via SuperPDPClient.update_vat_regime when it changes.
			"fieldname": "etransactions_vat_regime",
			"label": _("VAT Regime (e-reporting)"),
			"insert_after": "etransactions_electronic_address",
			"fieldtype": "Select",
			"options": "\nmonthly\nquarterly\nsimplified\nvat_exemption",
			"description": _(
				"VAT regime declared to the accredited platform; it sets the e-reporting "
				"cadence to the French tax administration (PPF)."
			),
		},
		{
			"fieldname": "etransactions_mentions_section",
			"label": _("Mandatory French Invoice Mentions"),
			"fieldtype": "Section Break",
			"insert_after": "etransactions_vat_regime",
			"collapsible": 1,
			"description": _(
				"Legal mentions required on French invoices (BR-FR-05). Left blank, "
				"standard legal default texts are used."
			),
		},
		{
			"fieldname": "etransactions_mention_late_penalty",
			"label": _("Late-Payment Penalties (PMD)"),
			"fieldtype": "Small Text",
			"insert_after": "etransactions_mentions_section",
		},
		{
			"fieldname": "etransactions_mention_recovery_costs",
			"label": _("Recovery Costs (PMT)"),
			"fieldtype": "Small Text",
			"insert_after": "etransactions_mention_late_penalty",
		},
		{
			"fieldname": "etransactions_mention_discount",
			"label": _("Early-Payment Discount (AAB)"),
			"fieldtype": "Small Text",
			"insert_after": "etransactions_mention_recovery_costs",
		},
]

customer_group_fields = [
	{
		"fieldname": "accredited_platform_override",
		"label": _("eTransactions Accredited Platform Override"),
		"fieldtype": "Link",
		"options": "eTransactions Accredited Platform",
		"insert_after": "parent_customer_group",
		"description": _("Override the default eTransactions Accredited Platform for customers in this group"),
	},
]

# Suppliers need identification for incoming-invoice matching; routing is the
# buyer's (company's) concern, so no directory fields here. The eTransactions tab
# hosts the lighter readiness indicator above the natively-edited fields.
supplier_fields = [
	{
		"fieldname": "siren_number",
		"label": _("SIREN Number"),
		"fieldtype": "Data",
		"insert_after": "tax_id",
		"length": 9,
	},
	{
		"fieldname": "etransactions_tab",
		"fieldtype": "Tab Break",
		"label": _("eTransactions"),
		"insert_after": "default_price_list",
	},
	{
		"fieldname": "etransactions_wizard_html",
		"fieldtype": "HTML",
		"insert_after": "etransactions_tab",
	},
	{
		"fieldname": "etransactions_electronic_address_scheme",
		"label": _("Electronic Address Scheme"),
		"insert_after": "etransactions_wizard_html",
		"fieldtype": "Link",
		"options": "Common Code",
	},
	{
		"fieldname": "etransactions_electronic_address",
		"label": _("Electronic Address"),
		"insert_after": "etransactions_electronic_address_scheme",
		"fieldtype": "Data",
		"depends_on": "etransactions_electronic_address_scheme",
	},
]

# An Address represents a single establishment. Its SIRET (the standard
# `siret_number` field added by erpnext's France regional setup) ties it to a
# routing line in the accredited-platform directory; the buyer reference (BT-10
# service code / "code service exécutant") is establishment-specific for B2G.
address_fields = [
	{
		"fieldname": "etransactions_section",
		"label": _("eTransactions"),
		"fieldtype": "Section Break",
		"insert_after": "siret_number",
		"collapsible": 1,
	},
	{
		"fieldname": "etransactions_buyer_reference",
		"label": _("Buyer Reference"),
		"fieldtype": "Data",
		"insert_after": "etransactions_section",
		"description": _("Service code (code service exécutant, BT-10) for this establishment. Overrides the customer-level default."),
	},
]

MASTER_DATA_FIELDS = {
	"Customer": customer_fields,
	"Company": company_fields,
	"Customer Group": customer_group_fields,
	"Address": address_fields,
	"Supplier": supplier_fields,
}