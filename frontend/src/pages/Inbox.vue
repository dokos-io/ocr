<template>
	<div class="flex h-full flex-col">
		<div class="flex flex-wrap items-end gap-3 border-b border-gray-200 bg-white px-5 py-3">
			<FormControl
				v-model="filters.status"
				type="select"
				:label="__('Status')"
				:options="statusOptions"
				@change="inbox.reload()"
			/>
			<FormControl
				v-model="filters.source"
				type="select"
				:label="__('Source')"
				:options="sourceOptions"
				@change="inbox.reload()"
			/>
			<div class="w-48">
				<LinkField
					doctype="Company"
					:modelValue="filters.company"
					:label="__('Company')"
					:placeholder="__('All companies')"
					@update:modelValue="onCompanyChange"
				/>
			</div>
			<div class="space-y-1.5">
				<label class="block text-xs text-gray-600">{{ __("Received between") }}</label>
				<DateRangePicker
					:modelValue="dateRange"
					:placeholder="__('Any date')"
					@update:modelValue="onDateRange"
				/>
			</div>
			<div class="ml-auto w-56">
				<FormControl
					v-model="filters.search"
					type="text"
					:label="__('Search')"
					:placeholder="__('Subject or sender')"
					@input="onSearch"
				/>
			</div>
		</div>

		<ListView
			class="flex-1"
			:columns="columns"
			:rows="rows"
			row-key="name"
			:options="{ selectable: false, showTooltip: false, onRowClick: openDetail }"
		/>

		<InboxDetailDrawer v-model="drawerOpen" :name="selected" @changed="inbox.reload()" />
	</div>
</template>

<script setup>
import { computed, reactive, ref } from "vue"
import { createResource, DateRangePicker, ListView } from "frappe-ui"
import InboxDetailDrawer from "@/components/InboxDetailDrawer.vue"
import LinkField from "@/components/LinkField.vue"

const selected = ref(null)
const drawerOpen = ref(false)
const dateRange = ref("")

const filters = reactive({
	status: "To Triage",
	source: "",
	company: "",
	from_date: "",
	to_date: "",
	search: "",
})

const statusOptions = [
	{ label: __("To Triage"), value: "To Triage" },
	{ label: __("In Progress"), value: "In Progress" },
	{ label: __("Processed"), value: "Processed" },
	{ label: __("Archived"), value: "Archived" },
]

const inbox = createResource({
	url: "etransactions.etransactions_hub.api.get_inbox",
	method: "GET",
	makeParams: () => ({
		status: filters.status,
		source: filters.source || null,
		company: filters.company || null,
		from_date: filters.from_date || null,
		to_date: filters.to_date || null,
		search: filters.search || null,
	}),
	auto: true,
})

function onCompanyChange(company) {
	filters.company = company
	inbox.reload()
}

const sourceOptions = computed(() => {
	const sources = [...new Set((inbox.data || []).map((item) => item.source).filter(Boolean))]
	return [{ label: __("All sources"), value: "" }, ...sources.map((s) => ({ label: __(s), value: s }))]
})

const columns = [
	{ label: __("Subject"), key: "subject", width: "2fr" },
	{ label: __("Sender"), key: "sender", width: "1.5fr" },
	{ label: __("Source"), key: "source", width: "1fr" },
	{ label: __("Status"), key: "status", width: "1fr" },
	{ label: __("Received"), key: "received", width: "1fr", align: "right" },
]

const rows = computed(() =>
	(inbox.data || []).map((item) => ({
		name: item.name,
		subject: item.title || item.subject || item.name,
		sender: item.sender || __(item.source || "Manual Upload"),
		source: __(item.source || ""),
		status: __(item.status),
		received: relativeTime(item.creation),
	}))
)

function openDetail(row) {
	selected.value = row.name
	drawerOpen.value = true
}

function onDateRange(value) {
	dateRange.value = value
	const [from, to] = (value || "").split(",")
	filters.from_date = from || ""
	filters.to_date = to || ""
	inbox.reload()
}

let searchTimer = null
function onSearch() {
	clearTimeout(searchTimer)
	searchTimer = setTimeout(() => inbox.reload(), 300)
}

function relativeTime(timestamp) {
	if (!timestamp) return ""
	const seconds = (Date.now() - new Date(timestamp).getTime()) / 1000
	if (seconds < 3600) return __("{0} min ago", [Math.max(1, Math.round(seconds / 60))])
	if (seconds < 86400) return __("{0} h ago", [Math.round(seconds / 3600)])
	return __("{0} d ago", [Math.round(seconds / 86400)])
}
</script>
