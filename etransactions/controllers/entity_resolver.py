import frappe
import difflib

class InvoiceEntityResolverMixin:
	"""Shared logic for resolving Supplier and Company records from raw text."""
	
	def resolve_supplier(self, seller_name: str, tax_id: str = None) -> str:
		supplier = None
		
		# 1. Match by Tax ID
		if tax_id:
			supplier = frappe.db.get_value("Supplier", {"tax_id": tax_id})

		# 2. Direct Name Match
		if not supplier and seller_name:
			supplier = frappe.db.get_value("Supplier", seller_name)

		# 3. Substring Match (Split Name)
		if not supplier and seller_name and len(seller_name.split(" ")) > 1:
			for substring in seller_name.split(" "):
				if supplier := frappe.db.get_value("Supplier", substring):
					break

		# 4. Fuzzy Match
		if not supplier and seller_name:
			existing_suppliers = frappe.get_all("Supplier", filters={"disabled": 0}, fields=["name", "supplier_name"])
			existing_supplier_dict = {s.supplier_name: s.name for s in existing_suppliers}
			
			names = list(existing_supplier_dict.keys())
			if names:
				matches = difflib.get_close_matches(seller_name.lower(), [n.lower() for n in names], n=1, cutoff=0.9)
				if matches:
					# Find original casing from the lower-case match
					best_match_name = next(n for n in names if n.lower() == matches[0])
					supplier = existing_supplier_dict.get(best_match_name)

		return supplier if (supplier and frappe.db.exists("Supplier", supplier)) else ""

	def resolve_company(self, receiver_name: str, receiver_address: str = "") -> str:
		company = None
		companies_list = frappe.get_all("Company", pluck="name")
		companies_map = {c.lower(): c for c in companies_list}
		
		r_name = (receiver_name or "").lower()
		r_addr = (receiver_address or "").lower()

		# 1. Fuzzy Match Name
		if match := difflib.get_close_matches(r_name, list(companies_map.keys()), cutoff=0.9):
			company = companies_map[match[0]]

		# 2. Fuzzy Match Address
		if not company and (match := difflib.get_close_matches(r_addr, list(companies_map.keys()), cutoff=0.9)):
			company = companies_map[match[0]]

		# 3. Substring Containment
		if not company:
			for c_lower, c_orig in companies_map.items():
				if c_lower in r_name or c_lower in r_addr:
					company = c_orig
					break

		# 4. Fallback to single company
		if not company and len(companies_list) == 1:
			company = companies_list[0]

		return company or ""