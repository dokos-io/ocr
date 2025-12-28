import frappe

@frappe.whitelist()
def create_basket_for_expense(file):
	print("create_basket_for_expense", file)