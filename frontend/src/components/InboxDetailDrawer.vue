<template>
	<div v-if="open" class="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true">
		<div class="absolute inset-0 bg-black/30" @click="close"></div>
		<section
			:aria-label="__('Item detail')"
			class="relative flex h-full w-full max-w-2xl flex-col bg-white shadow-xl"
		>
			<template v-if="detail.data">
				<div class="flex items-start justify-between border-b border-gray-200 px-4 py-3">
					<div class="min-w-0">
						<h2 class="truncate text-base font-semibold text-gray-900">
							{{ detail.data.item.title || detail.data.item.name }}
						</h2>
						<p class="truncate text-xs text-gray-600">
							{{ detail.data.item.sender }} · {{ __(detail.data.item.source || "") }}
						</p>
					</div>
					<Button variant="ghost" icon="x" :label="__('Close')" @click="close" />
				</div>

				<div class="flex flex-shrink-0 gap-2 border-b border-gray-200 px-4 py-2">
					<Button variant="solid" :loading="acting === 'invoice'" @click="createSupplierInvoice">
						{{ __("Create Supplier Invoice") }}
					</Button>
					<Button @click="requestDialogOpen = true">{{ __("Create Request") }}</Button>
					<Button variant="ghost" :loading="acting === 'archive'" @click="archive">
						{{ __("Archive") }}
					</Button>
				</div>

				<p
					v-if="feedback"
					class="border-b border-gray-200 bg-green-50 px-4 py-2 text-sm text-green-800"
					aria-live="polite"
				>
					{{ feedback }}
				</p>

				<div class="flex flex-1 overflow-hidden">
					<div class="flex-1 overflow-y-auto p-4">
						<article
							v-for="communication in detail.data.communications"
							:key="communication.name"
							class="mb-4 rounded border border-gray-200"
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
						<p v-if="!detail.data.communications.length" class="text-sm text-gray-600">
							{{ __("No email content for this item.") }}
						</p>
					</div>
					<aside
						:aria-label="__('Attached files')"
						class="w-64 flex-shrink-0 overflow-y-auto border-l border-gray-200 p-3"
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
			<p v-else class="p-6 text-sm text-gray-600">{{ __("Loading…") }}</p>

			<RequestDialog v-model="requestDialogOpen" :defaults="requestDefaults" @created="onRequestCreated" />
		</section>
	</div>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import { createResource } from "frappe-ui"
import RequestDialog from "@/components/RequestDialog.vue"
import { counts, runDocMethod } from "@/data/hub"

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	name: { type: String, default: "" },
})

const emit = defineEmits(["update:modelValue", "changed"])

const open = computed(() => props.modelValue && !!props.name)
const acting = ref("")
const feedback = ref("")
const requestDialogOpen = ref(false)

const detail = createResource({
	url: "etransactions.etransactions_hub.api.get_inbox_item",
	method: "GET",
	makeParams: () => ({ name: props.name }),
})

watch(
	() => [props.modelValue, props.name],
	([isOpen, name]) => {
		feedback.value = ""
		if (isOpen && name) {
			detail.reload()
		}
	}
)

const requestDefaults = computed(() => ({
	subject: detail.data?.item?.subject || "",
	inbox_item: props.name,
}))

function close() {
	emit("update:modelValue", false)
}

async function createSupplierInvoice() {
	acting.value = "invoice"
	try {
		await runDocMethod("Accounting Inbox Item", props.name, "create_supplier_invoice")
		feedback.value = __("Supplier invoice creation started. Find it in the invoices basket.")
		afterAction()
	} catch (exception) {
		feedback.value = exception.messages?.join("\n") || exception.message
	} finally {
		acting.value = ""
	}
}

async function archive() {
	acting.value = "archive"
	try {
		await runDocMethod("Accounting Inbox Item", props.name, "archive")
		feedback.value = __("Item archived.")
		afterAction()
	} catch (exception) {
		feedback.value = exception.messages?.join("\n") || exception.message
	} finally {
		acting.value = ""
	}
}

function onRequestCreated(name) {
	feedback.value = __("Accounting Request {0} created.", [name])
	afterAction()
}

function afterAction() {
	detail.reload()
	counts.reload()
	emit("changed")
}

function relativeTime(timestamp) {
	if (!timestamp) return ""
	const seconds = (Date.now() - new Date(timestamp).getTime()) / 1000
	if (seconds < 3600) return __("{0} min ago", [Math.max(1, Math.round(seconds / 60))])
	if (seconds < 86400) return __("{0} h ago", [Math.round(seconds / 3600)])
	return __("{0} d ago", [Math.round(seconds / 86400)])
}
</script>
