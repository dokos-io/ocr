from frappe import _lt

# The JSON subject renders this through Jinja's `_()`; referenced here so it is extracted.
SUBJECT = _lt("New Supplier Invoice created from a received e-invoice: {0}")


def get_context(context):
	pass
