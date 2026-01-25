app_name = "etransactions"
app_title = "eTransactions"
app_publisher = "Dokos SAS"
app_description = "eTransactions application for Dokos"
app_email = "hello@dokos.io"
app_license = "agpl-3.0"
required_apps = ["erpnext"]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/etransactions/css/etransactions.css"
app_include_js = "etransactions.bundle.js"
app_include_css = "etransactions.bundle.css"

# include js, css files in header of web template
# web_include_css = "/assets/etransactions/css/etransactions.css"
# web_include_js = "/assets/etransactions/js/etransactions.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "etransactions/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
doctype_js = {
	"Communication" : "public/js/communication.js",
	"Purchase Invoice": "public/js/purchase_invoice.js",
	"Purchase Order": "public/js/purchase_order.js",
}

doctype_list_js = {
	"Expense" : "public/js/expense_list.js"
}

# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "etransactions/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
#	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
#	"methods": "etransactions.utils.jinja_methods",
#	"filters": "etransactions.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "etransactions.install.before_install"
after_install = "etransactions.install.after_install"

after_migrate = "etransactions.migrate.after_migrate"

importable_doctypes = ["eTransaction Profile"]

# Uninstallation
# ------------

# before_uninstall = "etransactions.uninstall.before_uninstall"
# after_uninstall = "etransactions.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "etransactions.utils.before_app_install"
# after_app_install = "etransactions.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "etransactions.utils.before_app_uninstall"
# after_app_uninstall = "etransactions.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "etransactions.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
#	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
#	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
#	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

doc_events = {
	"Purchase Order": {
		"on_update": [
			"etransactions.etransactions.doctype.pending_purchase_invoice.pending_purchase_invoice.register_purchase_order_items",
			"etransactions.etransactions.doctype.pending_purchase_invoice.pending_purchase_invoice.set_pending_purchase_order_status"
		],
		"on_submit": [
			"etransactions.etransactions.doctype.pending_purchase_invoice.pending_purchase_invoice.set_pending_purchase_order_status"
		],
		"on_cancel": [
			"etransactions.etransactions.doctype.ocr_request.ocr_request.update_ocr_request_status",
			"etransactions.etransactions.doctype.pending_purchase_invoice.pending_purchase_invoice.set_pending_purchase_order_status"
		],
		"on_trash": [
			"etransactions.overrides.purchase_order.on_trash",
		]
	},
	"Purchase Invoice": {
		"validate": [
			"etransactions.overrides.purchase_invoice.validate_over_billing",
		],
		"before_submit": [
			"etransactions.etransactions.doctype.pending_purchase_invoice.pending_purchase_invoice.validate_total",
			"etransactions.overrides.purchase_invoice.validate_over_billing",
		],
		"on_submit": [
			"etransactions.etransactions.doctype.ocr_request.ocr_request.update_ocr_request_status",
			"etransactions.etransactions.doctype.pending_purchase_invoice.pending_purchase_invoice.set_pending_purchase_order_status",
		],
		"on_cancel": [
			"etransactions.etransactions.doctype.ocr_request.ocr_request.update_ocr_request_status",
			"etransactions.etransactions.doctype.pending_purchase_invoice.pending_purchase_invoice.set_pending_purchase_order_status"
		],
		"after_mapping": [
			"etransactions.overrides.purchase_invoice.after_mapping",
		]
	},
	"Purchase Receipt": {
		"on_submit": "etransactions.etransactions.doctype.pending_purchase_invoice.pending_purchase_invoice.auto_match_with_purchase_receipt",
		"on_cancel": "etransactions.etransactions.doctype.pending_purchase_invoice.pending_purchase_invoice.remove_link_with_pending_purchase_invoices",
		"on_change": "etransactions.etransactions.doctype.pending_purchase_invoice.pending_purchase_invoice.remove_link_with_pending_purchase_invoices"
	},
	"Pending Purchase Invoice": {
		"on_close": "etransactions.etransactions.doctype.ocr_request.ocr_request.update_ocr_request_status",
	},
	"Sales Invoice": {
		"before_save": "etransactions.overrides.sales_invoice.before_save",
	}
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	# "all": [
	# 	"etransactions.tasks.all"
	# ],
	"daily": [
		"etransactions.etransactions.doctype.ocr_purchase_invoice_basket.ocr_purchase_invoice_basket.check_ocr_basket_status"
	],
	"hourly": [
		"etransactions.etransactions.doctype.ocr_request.ocr_request.check_pending_analysis"
	],
	# "weekly": [
	# 	"etransactions.tasks.weekly"
	# ],
	# "monthly": [
	# 	"etransactions.tasks.monthly"
	# ],
}

# Testing
# -------

before_tests = "etransactions.install.before_tests"

# Overriding Methods
# ------------------------------
#
override_whitelisted_methods = {
	"erpnext.stock.get_item_details.get_item_details": "etransactions.overrides.get_item_details"
}
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
#	"Task": "etransactions.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["etransactions.utils.before_request"]
# after_request = ["etransactions.utils.after_request"]
# Job Events
# ----------
# before_job = ["etransactions.utils.before_job"]
# after_job = ["etransactions.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
#	{
#		"doctype": "{doctype_1}",
#		"filter_by": "{filter_by}",
#		"redact_fields": ["{field_1}", "{field_2}"],
#		"partial": 1,
#	},
#	{
#		"doctype": "{doctype_2}",
#		"filter_by": "{filter_by}",
#		"partial": 1,
#	},
#	{
#		"doctype": "{doctype_3}",
#		"strict": False,
#	},
#	{
#		"doctype": "{doctype_4}"
#	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
#	"etransactions.auth.validate"
# ]

export_python_type_annotations = True
