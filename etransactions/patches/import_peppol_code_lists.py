import frappe
from etransactions.install import import_peppol_participant_identifier_schemes

def execute():
	import_peppol_participant_identifier_schemes()
