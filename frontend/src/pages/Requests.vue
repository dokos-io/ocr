<template>
	<div class="flex h-full flex-col">
		<div class="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-2">
			<fieldset class="flex gap-1" :aria-label="__('Request scope')">
				<Button
					v-for="option in scopeOptions"
					:key="option.value"
					:variant="scope === option.value ? 'solid' : 'ghost'"
					:aria-pressed="scope === option.value"
					@click="setScope(option.value)"
				>
					{{ option.label }}
				</Button>
			</fieldset>
			<Button variant="solid" @click="requestDialogOpen = true">{{ __("New Request") }}</Button>
		</div>

		<p v-if="feedback" class="border-b border-gray-200 bg-green-50 px-4 py-2 text-sm text-green-800" aria-live="polite">
			{{ feedback }}
		</p>

		<div class="flex flex-1 gap-4 overflow-x-auto bg-gray-50 p-5">
			<section
				v-for="column in columns"
				:key="column.status"
				:aria-label="column.label"
				class="flex w-72 flex-shrink-0 flex-col rounded-lg border border-gray-200 bg-white shadow-sm"
			>
				<h2 class="flex items-center justify-between gap-2 rounded-t-lg border-b border-gray-200 px-3 py-2 text-sm font-semibold text-gray-900">
					<span class="flex items-center gap-2">
						<span class="h-2 w-2 rounded-full" :class="column.dotClass"></span>
						{{ column.label }}
					</span>
					<Badge :theme="column.theme" variant="subtle">{{ column.requests.length }}</Badge>
				</h2>
				<ul role="list" class="flex-1 space-y-2 overflow-y-auto p-3">
					<li v-for="request in column.requests" :key="request.name">
						<article
							class="rounded-md border border-l-4 border-gray-200 p-3 transition-shadow hover:shadow-sm focus-within:ring-2 focus-within:ring-brand-500"
							:class="column.borderClass"
						>
							<button class="w-full text-left" @click="openDetail(request)">
								<div class="flex items-start justify-between gap-2">
									<span class="text-sm font-medium text-gray-900">{{ request.subject }}</span>
									<Badge v-if="isOverdue(request)" theme="red" variant="subtle">{{ __("Overdue") }}</Badge>
								</div>
								<p class="mt-1 text-xs text-gray-600">
									{{ __(request.request_type) }}
									<template v-if="request.context_party"> · {{ request.context_party }}</template>
									<template v-if="request.context_amount"> · {{ formatAmount(request.context_amount) }}</template>
								</p>
								<p v-if="request.due_date" class="mt-0.5 text-xs text-gray-600">
									{{ __("Due {0}", [request.due_date]) }}
								</p>
							</button>
							<div v-if="canResolve(request)" class="mt-2 flex gap-1">
								<Button
									size="sm"
									variant="ghost"
									:loading="resolving === request.name"
									@click="resolve(request)"
								>
									{{ __("Resolve") }}
								</Button>
							</div>
						</article>
					</li>
					<li v-if="!column.requests.length" class="p-2 text-xs text-gray-500">
						{{ __("No request") }}
					</li>
				</ul>
			</section>
		</div>

		<RequestDialog v-model="requestDialogOpen" @created="onRequestCreated" />
		<RequestDetailDrawer v-model="detailOpen" :request="detailRequest" @resolved="onResolved" />
	</div>
</template>

<script setup>
import { computed, ref } from "vue"
import { createResource } from "frappe-ui"
import RequestDialog from "@/components/RequestDialog.vue"
import RequestDetailDrawer from "@/components/RequestDetailDrawer.vue"
import { counts, runDocMethod } from "@/data/hub"

const scope = ref("mine")
const feedback = ref("")
const resolving = ref("")
const requestDialogOpen = ref(false)
const detailOpen = ref(false)
const detailRequest = ref({})

const scopeOptions = [
	{ label: __("Waiting on me"), value: "mine" },
	{ label: __("Raised by me"), value: "raised" },
	{ label: __("All"), value: "all" },
]

const requests = createResource({
	url: "etransactions.etransactions_hub.api.get_requests",
	method: "GET",
	makeParams: () => ({ scope: scope.value }),
	auto: true,
})

const statuses = [
	{ status: "Open", label: __("Open"), theme: "blue", dotClass: "bg-blue-500", borderClass: "border-l-blue-500" },
	{
		status: "Awaiting Response",
		label: __("Awaiting Response"),
		theme: "orange",
		dotClass: "bg-orange-400",
		borderClass: "border-l-orange-400",
	},
	{
		status: "Response Received",
		label: __("Response Received"),
		theme: "green",
		dotClass: "bg-green-500",
		borderClass: "border-l-green-500",
	},
	{ status: "Resolved", label: __("Resolved"), theme: "gray", dotClass: "bg-gray-400", borderClass: "border-l-gray-300" },
]

const columns = computed(() =>
	statuses.map((column) => ({
		...column,
		requests: (requests.data || []).filter((request) => request.status === column.status),
	}))
)

function setScope(value) {
	scope.value = value
	requests.reload()
}

function openDetail(request) {
	detailRequest.value = request
	detailOpen.value = true
}

function isOverdue(request) {
	if (!request.due_date || ["Resolved", "Closed", "Cancelled"].includes(request.status)) {
		return false
	}
	return new Date(request.due_date) < new Date(new Date().toDateString())
}

function canResolve(request) {
	return !["Resolved", "Closed", "Cancelled"].includes(request.status)
}

async function resolve(request) {
	resolving.value = request.name
	try {
		await runDocMethod("Accounting Request", request.name, "resolve")
		feedback.value = __("Request {0} resolved.", [request.name])
		requests.reload()
		counts.reload()
	} catch (exception) {
		feedback.value = exception.messages?.join("\n") || exception.message
	} finally {
		resolving.value = ""
	}
}

function onResolved(name) {
	feedback.value = __("Request {0} resolved.", [name])
	detailOpen.value = false
	requests.reload()
	counts.reload()
}

function onRequestCreated(name) {
	feedback.value = __("Accounting Request {0} created.", [name])
	requests.reload()
	counts.reload()
}

function formatAmount(amount) {
	return new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(amount)
}
</script>
