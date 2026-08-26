from frappe import N_ as _


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
		"depends_on": "eval:frappe.boot.einvoicing_enabled",
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
	# The E-invoicing Network switch drives the whole tab: the French routing
	# section shows for "ppf", the Peppol Endpoint section for "peppol".
	{
		"fieldname": "pa_identity_section",
		"label": _("Identity"),
		"fieldtype": "Section Break",
		"insert_after": "etransactions_wizard_html",
	},
	{
		"fieldname": "directory_type",
		"label": _("E-invoicing Network"),
		"fieldtype": "Select",
		# Stored values match the SuperPDP API contract ("peppol" | "ppf");
		# "ppf" is the French national directory (Portail Public de Facturation).
		"options": "\npeppol\nppf",
		"default": "ppf",
		"insert_after": "pa_identity_section",
		"description": _("The network this customer is reached on: the Peppol network, or the French national directory (PPF)."),
	},
	{
		"fieldname": "etransaction_profile",
		"label": "eTransaction Profile",
		"fieldtype": "Link",
		"options": "eTransaction Profile",
		"insert_after": "directory_type",
	},
	# --- French routing: discovered and maintained automatically by directory sync ---
	{
		"fieldname": "pa_directory_section",
		"label": _("Routing — managed automatically"),
		"fieldtype": "Section Break",
		"insert_after": "etransaction_profile",
		"collapsible": 1,
		"depends_on": 'eval:doc.directory_type!="peppol"',
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
		# private_inactive = VAT-registered business whose directory entry is no
		# longer active: it has no reachable routing line, so it is e-reported (B2C)
		# rather than e-invoiced, and re-synced on a shorter cadence.
		"options": "\nprivate\nprivate_inactive\npublic\nno",
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
	# The SIREN/SIRET actually used to query the directory, recorded at sync time.
	# A later change to the party's SIREN/SIRET means the routing lines belong to a
	# different legal entity — readiness flags it (a new record should be created).
	{
		"fieldname": "directory_query_siren",
		"label": _("Directory Query SIREN"),
		"fieldtype": "Data",
		"insert_after": "directory_update_date",
		"read_only": 1,
		"no_copy": 1,
		"hidden": 1,
	},
	{
		"fieldname": "directory_query_siret",
		"label": _("Directory Query SIRET"),
		"fieldtype": "Data",
		"insert_after": "directory_query_siren",
		"read_only": 1,
		"no_copy": 1,
		"hidden": 1,
	},
	# --- Peppol: the endpoint a Peppol participant is reached at ---
	# For Peppol, the ISO 6523 scheme + participant id ARE the routing address
	# (there is no French directory to sync), so they are the primary input here.
	{
		"fieldname": "pa_peppol_section",
		"label": _("Peppol Endpoint"),
		"fieldtype": "Section Break",
		"insert_after": "directory_query_siret",
		"depends_on": 'eval:doc.directory_type=="peppol"',
	},
	{
		"fieldname": "etransactions_electronic_address_scheme",
		"label": _("Peppol Endpoint Scheme"),
		"insert_after": "pa_peppol_section",
		"fieldtype": "Link",
		"options": "Common Code",
	},
	{
		"fieldname": "etransactions_electronic_address",
		"label": _("Peppol Endpoint ID"),
		"insert_after": "etransactions_electronic_address_scheme",
		"fieldtype": "Data",
		"depends_on": "etransactions_electronic_address_scheme",
	},
	# --- Advanced: network-neutral routing overrides, rarely touched ---
	{
		"fieldname": "pa_advanced_section",
		"label": _("Advanced"),
		"fieldtype": "Section Break",
		"insert_after": "etransactions_electronic_address",
		"collapsible": 1,
	},
	{
		"fieldname": "default_directory_line",
		"label": _("Default Directory Line"),
		"fieldtype": "Link",
		"options": "eInvoicing Directory Line",
		"insert_after": "pa_advanced_section",
		"description": _("Default routing line used when no establishment-specific line matches the invoice address."),
	},
	{
		"fieldname": "directory_pinned",
		"label": _("Directory Pinned"),
		"fieldtype": "Check",
		"insert_after": "default_directory_line",
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
]

company_fields = [
		# NB: Company.siren_number is a standard ERPNext field (company.json),
		# so it is not (re)declared here — only read by the CDAR/generator code.
		{
			"fieldname": "etransactions_tab",
			"fieldtype": "Tab Break",
			"label": _("eTransactions"),
			"insert_after": "connections_tab",
			"depends_on": "eval:frappe.boot.einvoicing_enabled",
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
		"depends_on": "eval:frappe.boot.einvoicing_enabled",
	},
]

# Suppliers need identification for incoming-invoice matching; routing and the
# electronic address (BT-34/BT-49) are the buyer's/seller's concern — a supplier is
# the seller on invoices we *receive*, so its endpoint is never emitted by anything
# we generate. The eTransactions tab therefore carries no endpoint/routing fields:
# just the lighter readiness indicator above the natively-edited identification
# fields (SIREN next to Tax ID, Tax ID, and SIRET on the Address).
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
		"depends_on": "eval:frappe.boot.einvoicing_enabled",
	},
	{
		"fieldname": "etransactions_wizard_html",
		"fieldtype": "HTML",
		"insert_after": "etransactions_tab",
	},
]

# An Address represents a single establishment. Its SIRET (the standard
# `siret_number` field added by erpnext's France regional setup) ties it to a
# routing line in the accredited-platform directory; the buyer reference (BT-10
# service code / "code service exécutant") is establishment-specific for B2G.
address_fields = [
	{
		"fieldname": "etransactions_tab",
		"fieldtype": "Tab Break",
		"label": _("eTransactions"),
		"insert_after": "siret_number",
		"depends_on": "eval:frappe.boot.einvoicing_enabled",
	},
	{
		"fieldname": "etransactions_buyer_reference",
		"label": _("Buyer Reference"),
		"fieldtype": "Data",
		"insert_after": "etransactions_tab",
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