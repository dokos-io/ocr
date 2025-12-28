from etransactions.install import add_custom_fields

def after_migrate():
	add_custom_fields()