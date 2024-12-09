<template>
<div>
	<div class="my-8 d-flex">
		<Field :df="{fieldtype: 'Check', fieldname: 'purchase_order', label: __('Purchase Order') }" :model-value="purchase_order" />
		<Field :df="{fieldtype: 'Check', fieldname: 'purchase_receipt', label: __('Purchase Receipt') }" :model-value="purchase_receipt" class="ml-5"/>
	</div>

	<div class="my-8">
		<Field :df="{fieldtype: 'Table', fieldname: 'vouchers', label: __('Select matching documents'), fields: vouchers_fields, data: vouchers, cannot_add_rows: true}" @row-checked="voucher_checked"/>
	</div>

	<div class="my-8">
		<Field :df="{fieldtype: 'Table', fieldname: 'items', label: __('Select matching documents'), fields: items_fields, hidden: hide_items_table, data: items}" />
	</div>

	<div class="my-8 text-right">
		<Field :df="{fieldtype: 'Button', fieldname: 'submit', label: __('Create a Purchase Invoice'), primary: true, click:() => {button_click()}}" />
	</div>
</div>
</template>

<script setup>
import { ref } from "vue";
import Field from "./Field.vue";

import { computed } from 'vue';

const props = defineProps({
	filters: {
		type: Object,
		default: {},
	},
	transaction: {
		type: Object,
		default: {},
		reqd: true
	},
})

const vouchers = ref([]);
const items = ref([]);
const items_fields = ref([]);
const hide_items_table = ref(true);
const purchase_order = ref(props.filters.purchase_order);
const purchase_receipt = ref(props.filters.purchase_receipt);
const selected_rows = ref([]);

const document_types = computed(() => {
	po = purchase_order ? "purchase_order" : null;
	pr = purchase_receipt ? "purchase_receipt" : null;
	return [po, pr].filter(i => !!i)
})

const vouchers_fields = [
	{
		label: __("Reference DocType"),
		fieldname: "doctype",
		fieldtype: "Data",
		read_only: true,
		hidden: true,
		in_list_view: true,
	},
	{
		label: __("Document Name"),
		fieldname: "docname",
		fieldtype: "Data",
		read_only: true,
		in_list_view: true,
		columns: 2
	},
	{
		label: __("Supplier"),
		fieldname: "supplier",
		fieldtype: "Data",
		read_only: true,
		in_list_view: true,
		columns: 2
	},
	{
		label: __("Date"),
		fieldname: "transaction_date",
		fieldtype: "Data",
		read_only: true,
		in_list_view: true,
		columns: 1
	},
	{
		label: __("Net Total"),
		fieldname: "net_total",
		fieldtype: "Currency",
		read_only: true,
		in_list_view: true,
		columns: 2
	},
	{
		label: __("Grand Total"),
		fieldname: "grand_total",
		fieldtype: "Currency",
		read_only: true,
		in_list_view: true,
		columns: 2
	},
	{
		label: __("Billed %"),
		fieldname: "per_billed",
		fieldtype: "Percent",
		read_only: true,
		in_list_view: true,
		columns: 1
	},
];


get_matching_vouchers();

async function get_matching_vouchers() {
	let matching_vouchers = await frappe.call({
		method:
			"ocr.ocr.doctype.pending_purchase_invoice.pending_purchase_invoice.get_matching_documents",
		args: {
			purchase_invoice: props.transaction.name,
			document_types: document_types.value,
			filter_by_reference_date: props.filters.filter_by_reference_date,
			from_reference_date: props.filters.from_reference_date,
			to_reference_date: props.filters.to_reference_date
		},
	}).then(result => result.message);
	vouchers.value = matching_vouchers || [];
}


async function voucher_checked(rows) {
	selected_rows.value = rows.length ? rows.map(r => r.doc) : [];

	if (!rows.length) {
		hide_items_table.value = true;
	}

	await frappe.model.with_doctype("Purchase Order Item");
	await frappe.model.with_doctype("Purchase Receipt Item");
	const meta = frappe.get_meta("Purchase Order Item");

	items_fields.value = meta.fields;
	hide_items_table.value = false;

	const children = await get_children_rows(rows);
	items.value = children.flat();
}

async function get_children_rows(rows) {
	return Promise.all(
		rows.map(async (row) => {
			const document_name = row.doc.docname;
			const reference_doctype = row.doc.doctype;

			await frappe.model.with_doc(reference_doctype, document_name);
			const doc = frappe.get_doc(reference_doctype, document_name);
			child_rows = doc.items.map(i => {
				i["original_name"] = i["name"]
				delete i["name"];
				return i;
			})

			return child_rows
		})
	)
}

function button_click() {
	frappe.call({
		method:
			"ocr.ocr.doctype.ocr_reconciliation_dashboard.ocr_reconciliation_dashboard.create_purchase_invoice",
		args: {
			ocr_request: props.transaction.name,
			selected_rows: selected_rows.value,
			items: items.value,
		},
	}).then(() => {
		frappe.show_alert({
			message: __("Purchase Invoice Created"),
			indicator: "green"
		})
	});
}

</script>