import { createApp } from 'vue';

import MatchTab from "./MatchTab.vue";

frappe.provide("ocr.pending_invoice");

ocr.pending_invoice.match_tab = class MatchTabComponent {
	/*
		Filters: purchase_order, purchase_receipt, filter_by_reference_date, from_reference_date, to_reference_date
	*/
	constructor(wrapper, transaction, filters) {
		console.log(wrapper, transaction, filters)
		let app = createApp(MatchTab, {
			filters: filters,
			transaction: transaction
		})
		SetVueGlobals(app);
		app.mount(wrapper)
	}
}