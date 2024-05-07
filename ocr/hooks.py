app_name = "ocr"
app_title = "OCR"
app_publisher = "Dokos SAS"
app_description = "OCR application for Dokos"
app_email = "hello@dokos.io"
app_license = "agpl-3.0"
required_apps = ["erpnext"]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/ocr/css/ocr.css"
app_include_js = "ocr.bundle.js"

# include js, css files in header of web template
# web_include_css = "/assets/ocr/css/ocr.css"
# web_include_js = "/assets/ocr/js/ocr.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "ocr/public/scss/website"

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
# app_include_icons = "ocr/public/icons.svg"

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
#	"methods": "ocr.utils.jinja_methods",
#	"filters": "ocr.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "ocr.install.before_install"
after_install = "ocr.install.after_install"

after_migrate = "ocr.migrate.after_migrate"

# Uninstallation
# ------------

# before_uninstall = "ocr.uninstall.before_uninstall"
# after_uninstall = "ocr.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "ocr.utils.before_app_install"
# after_app_install = "ocr.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "ocr.utils.before_app_uninstall"
# after_app_uninstall = "ocr.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "ocr.notifications.get_notification_config"

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
		"on_update": "ocr.ocr.doctype.ocr_request.ocr_request.on_purchase_order_update",
		"on_submit": "ocr.ocr.doctype.ocr_request.ocr_request.after_purchase_order_submit",
	}
}

# Scheduled Tasks
# ---------------

scheduler_events = {
	"all": [
		"ocr.ocr.doctype.ocr_purchase_invoice_basket.ocr_purchase_invoice_basket.check_requests_completion"
	],
	# "daily": [
	# 	"ocr.tasks.daily"
	# ],
	"hourly": [
		"ocr.ocr.doctype.ocr_request.ocr_request.check_pending_analysis"
	],
	# "weekly": [
	# 	"ocr.tasks.weekly"
	# ],
	# "monthly": [
	# 	"ocr.tasks.monthly"
	# ],
}

# Testing
# -------

# before_tests = "ocr.install.before_tests"

# Overriding Methods
# ------------------------------
#
override_whitelisted_methods = {
	"erpnext.stock.get_item_details.get_item_details": "ocr.overrides.get_item_details"
}
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
#	"Task": "ocr.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["ocr.utils.before_request"]
# after_request = ["ocr.utils.after_request"]
# Job Events
# ----------
# before_job = ["ocr.utils.before_job"]
# after_job = ["ocr.utils.after_job"]

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
#	"ocr.auth.validate"
# ]

export_python_type_annotations = True
