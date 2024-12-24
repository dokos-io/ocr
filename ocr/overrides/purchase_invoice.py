def after_mapping(doc, method, purchase_order):
	if purchase_order.get("pending_purchase_invoice"):
		doc.pending_purchase_invoice = purchase_order.pending_purchase_invoice
		doc.ocr_original_file = purchase_order.get("ocr_original_file")