import frappe
from frappe import _
from frappe.model.document import Document


class eInvoicingDirectoryLine(Document):
    # begin: auto-generated types
    # This code is auto-generated. Do not modify anything in this block.

    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from frappe.types import DF

        address: DF.Link | None
        commitment_required: DF.Check
        customer: DF.Link | None
        identifier: DF.Data
        line_status: DF.Literal["upcoming", "active", "disabled", "inactive"]
        line_type: DF.Literal["siren", "siret", "routing_code", "suffix"]
        routing_code: DF.Data | None
        routing_code_name: DF.Data | None
        siren: DF.Data | None
        siret: DF.Data | None
        supplier: DF.Link | None
    # end: auto-generated types

    def validate(self):
        if bool(self.customer) == bool(self.supplier):
            frappe.throw(_("Set exactly one of Customer or Supplier on a directory line."))
