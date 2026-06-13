<template>
	<div v-if="open" class="fixed inset-0 z-40 flex justify-end" role="dialog" aria-modal="true">
		<div class="absolute inset-0 bg-black/30" @click="close"></div>
		<section
			:aria-label="__('Request detail')"
			class="relative flex h-full w-full max-w-md flex-col bg-white shadow-xl"
		>
			<div class="flex items-start justify-between border-b border-gray-200 px-4 py-3">
				<div class="min-w-0">
					<h2 class="truncate text-base font-semibold text-gray-900">{{ request.subject }}</h2>
					<p class="text-xs text-gray-600">{{ request.name }}</p>
				</div>
				<Button variant="ghost" icon="x" :label="__('Close')" @click="close" />
			</div>

			<p
				v-if="feedback"
				class="border-b border-gray-200 bg-green-50 px-4 py-2 text-sm text-green-800"
				aria-live="polite"
			>
				{{ feedback }}
			</p>

			<div class="flex-1 space-y-4 overflow-y-auto px-4 py-4">
				<dl class="grid grid-cols-3 gap-x-3 gap-y-2 text-sm">
					<dt class="text-gray-500">{{ __("Status") }}</dt>
					<dd class="col-span-2">
						<Badge variant="subtle">{{ __(request.status) }}</Badge>
					</dd>
					<dt class="text-gray-500">{{ __("Type") }}</dt>
					<dd class="col-span-2 text-gray-900">{{ __(request.request_type) }}</dd>
					<template v-if="request.context_party">
						<dt class="text-gray-500">{{ __("Party") }}</dt>
						<dd class="col-span-2 text-gray-900">{{ request.context_party }}</dd>
					</template>
					<template v-if="request.context_amount">
						<dt class="text-gray-500">{{ __("Amount") }}</dt>
						<dd class="col-span-2 text-gray-900">{{ request.context_amount }}</dd>
					</template>
					<template v-if="request.due_date">
						<dt class="text-gray-500">{{ __("Due date") }}</dt>
						<dd class="col-span-2 text-gray-900">{{ request.due_date }}</dd>
					</template>
					<dt class="text-gray-500">{{ __("Raised by") }}</dt>
					<dd class="col-span-2 text-gray-900">{{ request.raised_by }}</dd>
					<dt class="text-gray-500">{{ __("Assigned to") }}</dt>
					<dd class="col-span-2">
						<div v-if="assignees.length" class="flex flex-wrap items-center gap-1">
							<Avatar
								v-for="user in assignees"
								:key="user"
								:label="userLabel(user)"
								:image="userImage(user)"
								size="sm"
							/>
							<span class="text-gray-700">{{ assignees.map(userLabel).join(", ") }}</span>
						</div>
						<span v-else class="text-gray-500">{{ __("Nobody yet") }}</span>
					</dd>
				</dl>

				<div v-if="description">
					<h3 class="mb-1 text-xs font-medium text-gray-500">{{ __("Description") }}</h3>
					<p class="whitespace-pre-wrap text-sm text-gray-900">{{ description }}</p>
				</div>
			</div>

			<div v-if="canResolve" class="border-t border-gray-200 px-4 py-3">
				<Button variant="solid" :loading="resolving" @click="resolve">{{ __("Resolve") }}</Button>
			</div>
		</section>
	</div>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import { Avatar, createResource } from "frappe-ui"
import { assignableUsers, counts, runDocMethod } from "@/data/hub"

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	request: { type: Object, default: () => ({}) },
})

const emit = defineEmits(["update:modelValue", "resolved"])

const open = computed(() => props.modelValue && !!props.request?.name)
const feedback = ref("")
const resolving = ref(false)
const description = ref("")

const descriptionResource = createResource({
	url: "frappe.client.get_value",
	method: "GET",
	makeParams: () => ({
		doctype: "Accounting Request",
		filters: props.request.name,
		fieldname: "description",
	}),
})

watch(
	() => [props.modelValue, props.request?.name],
	async ([isOpen, name]) => {
		feedback.value = ""
		description.value = ""
		if (isOpen && name) {
			const result = await descriptionResource.reload()
			description.value = result?.description || ""
		}
	}
)

const assignees = computed(() => {
	try {
		return JSON.parse(props.request._assign || "[]")
	} catch (exception) {
		return []
	}
})

const canResolve = computed(
	() => !["Resolved", "Closed", "Cancelled"].includes(props.request.status)
)

function userLabel(name) {
	const user = (assignableUsers.data || []).find((u) => u.name === name)
	return user?.full_name || name
}

function userImage(name) {
	return (assignableUsers.data || []).find((u) => u.name === name)?.user_image
}

function close() {
	emit("update:modelValue", false)
}

async function resolve() {
	resolving.value = true
	try {
		await runDocMethod("Accounting Request", props.request.name, "resolve")
		feedback.value = __("Request {0} resolved.", [props.request.name])
		counts.reload()
		emit("resolved", props.request.name)
	} catch (exception) {
		feedback.value = exception.messages?.join("\n") || exception.message
	} finally {
		resolving.value = false
	}
}
</script>
