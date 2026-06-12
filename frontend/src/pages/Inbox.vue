<template>
	<div class="flex h-full">
		<section
			:aria-label="__('Inbox items')"
			class="flex w-80 flex-shrink-0 flex-col border-r border-gray-200 bg-white"
		>
			<div class="border-b border-gray-200 p-2">
				<FormControl
					v-model="statusFilter"
					type="select"
					:label="__('Status filter')"
					:options="statusOptions"
					@change="inbox.reload()"
				/>
			</div>
			<ul class="flex-1 overflow-y-auto" role="list">
				<li v-for="item in inbox.data || []" :key="item.name">
					<button
						class="w-full border-b border-gray-100 px-3 py-2 text-left hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-gray-500"
						:class="{ 'bg-gray-100': selected === item.name }"
						:aria-pressed="selected === item.name"
						@click="select(item.name)"
					>
						<div class="flex items-center justify-between gap-2">
							<span class="truncate text-sm font-medium text-gray-900">
								{{ item.title || item.subject || item.name }}
							</span>
							<Badge :theme="statusTheme(item.status)" variant="subtle">{{ __(item.status) }}</Badge>
						</div>
						<div class="mt-0.5 flex items-center justify-between gap-2 text-xs text-gray-600">
							<span class="truncate">{{ item.sender || __(item.source || "Manual Upload") }}</span>
							<span>{{ relativeTime(item.creation) }}</span>
						</div>
					</button>
				</li>
				<li v-if="!inbox.loading && !(inbox.data || []).length" class="p-4 text-sm text-gray-600">
					{{ __("Nothing to triage. Well done!") }}
				</li>
			</ul>
		</section>

		<section :aria-label="__('Item detail')" class="flex flex-1 flex-col overflow-hidden">
			<template v-if="detail.data">
				<div class="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-2">
					<div class="min-w-0">
						<h2 class="truncate text-base font-semibold text-gray-900">
							{{ detail.data.item.title || detail.data.item.name }}
						</h2>
						<p class="truncate text-xs text-gray-600">
							{{ detail.data.item.sender }} · {{ __(detail.data.item.source || "") }}
						</p>
					</div>
					<div class="flex flex-shrink-0 gap-2">
						<Button
							variant="solid"
							:loading="acting === 'invoice'"
							@click="createSupplierInvoice"
						>
							{{ __("Create Supplier Invoice") }}
						</Button>
						<Button @click="requestDialogOpen = true">{{ __("Create Request") }}</Button>
						<Button variant="ghost" :loading="acting === 'archive'" @click="archive">
							{{ __("Archive") }}
						</Button>
					</div>
				</div>

				<p v-if="feedback" class="border-b border-gray-200 bg-green-50 px-4 py-2 text-sm text-green-800" aria-live="polite">
					{{ feedback }}
				</p>

				<div class="flex flex-1 overflow-hidden">
					<div class="flex-1 overflow-y-auto p-4">
						<article
							v-for="communication in detail.data.communications"
							:key="communication.name"
							class="mb-4 rounded border border-gray-200 bg-white"
						>
							<div class="border-b border-gray-100 px-3 py-2 text-xs text-gray-600">
								{{ communication.sender }} · {{ relativeTime(communication.creation) }}
							</div>
							<iframe
								:srcdoc="communication.content"
								sandbox=""
								:title="__('Email content from {0}', [communication.sender])"
								class="h-64 w-full"
							></iframe>
						</article>
						<p
							v-if="!detail.data.communications.length"
							class="text-sm text-gray-600"
						>
							{{ __("No email content for this item.") }}
						</p>
					</div>
					<aside
						:aria-label="__('Attached files')"
						class="w-64 flex-shrink-0 overflow-y-auto border-l border-gray-200 bg-white p-3"
					>
						<h3 class="mb-2 text-sm font-semibold text-gray-900">{{ __("Files") }}</h3>
						<ul role="list" class="space-y-1">
							<li v-for="file in detail.data.files" :key="file.name">
								<a
									:href="file.file_url"
									target="_blank"
									rel="noopener"
									class="block truncate rounded px-2 py-1 text-sm text-gray-700 underline hover:bg-gray-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-500"
								>
									{{ file.file_name }}
								</a>
							</li>
						</ul>
						<p v-if="!detail.data.files.length" class="text-sm text-gray-600">
							{{ __("No file attached.") }}
						</p>
					</aside>
				</div>
			</template>
			<p v-else class="p-6 text-sm text-gray-600">
				{{ __("Select an inbox item to preview it.") }}
			</p>
		</section>

		<RequestDialog
			v-model="requestDialogOpen"
			:defaults="requestDefaults"
			@created="onRequestCreated"
		/>
	</div>
</template>

<script setup>
import { computed, ref } from "vue"
import { createResource } from "frappe-ui"
import RequestDialog from "@/components/RequestDialog.vue"
import { counts, runDocMethod } from "@/data/hub"

const statusFilter = ref("To Triage")
const selected = ref(null)
const acting = ref("")
const feedback = ref("")
const requestDialogOpen = ref(false)

const statusOptions = [
	{ label: __("To Triage"), value: "To Triage" },
	{ label: __("In Progress"), value: "In Progress" },
	{ label: __("Processed"), value: "Processed" },
	{ label: __("Archived"), value: "Archived" },
]

const inbox = createResource({
	url: "etransactions.accounting_hub.api.get_inbox",
	method: "GET",
	makeParams: () => ({ status: statusFilter.value }),
	auto: true,
})

const detail = createResource({
	url: "etransactions.accounting_hub.api.get_inbox_item",
	method: "GET",
	makeParams: () => ({ name: selected.value }),
})

const requestDefaults = computed(() => ({
	subject: detail.data?.item?.subject || "",
	inbox_item: selected.value,
}))

function select(name) {
	selected.value = name
	feedback.value = ""
	detail.reload()
}

async function createSupplierInvoice() {
	acting.value = "invoice"
	try {
		await runDocMethod("Accounting Inbox Item", selected.value, "create_supplier_invoice")
		feedback.value = __("Supplier invoice creation started. Find it in the invoices basket.")
		refresh()
	} catch (exception) {
		feedback.value = exception.messages?.join("\n") || exception.message
	} finally {
		acting.value = ""
	}
}

async function archive() {
	acting.value = "archive"
	try {
		await runDocMethod("Accounting Inbox Item", selected.value, "archive")
		feedback.value = __("Item archived.")
		refresh()
	} catch (exception) {
		feedback.value = exception.messages?.join("\n") || exception.message
	} finally {
		acting.value = ""
	}
}

function onRequestCreated(name) {
	feedback.value = __("Accounting Request {0} created.", [name])
	refresh()
}

function refresh() {
	inbox.reload()
	counts.reload()
	if (selected.value) {
		detail.reload()
	}
}

function relativeTime(timestamp) {
	if (!timestamp) return ""
	const seconds = (Date.now() - new Date(timestamp).getTime()) / 1000
	if (seconds < 3600) return __("{0} min ago", [Math.max(1, Math.round(seconds / 60))])
	if (seconds < 86400) return __("{0} h ago", [Math.round(seconds / 3600)])
	return __("{0} d ago", [Math.round(seconds / 86400)])
}

function statusTheme(status) {
	return { "To Triage": "blue", "In Progress": "orange", Processed: "green", Archived: "gray" }[
		status
	]
}
</script>
