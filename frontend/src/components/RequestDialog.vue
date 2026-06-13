<template>
	<Dialog v-model="open" :options="{ title: __('New Accounting Request') }">
		<template #body-content>
			<form class="space-y-4" @submit.prevent="create">
				<FormControl
					v-model="form.subject"
					type="text"
					:label="__('Subject')"
					required
					autocomplete="off"
				/>
				<FormControl
					v-model="form.request_type"
					type="select"
					:label="__('Request Type')"
					:options="requestTypes"
				/>
				<UserPicker v-model="form.assign_to" :label="__('Assign To')" />
				<div class="space-y-1.5">
					<label class="block text-xs text-gray-600">{{ __("Due Date") }}</label>
					<DatePicker
						:modelValue="form.due_date"
						:placeholder="__('Select date')"
						@update:modelValue="(value) => (form.due_date = value)"
					/>
				</div>
				<FormControl v-model="form.description" type="textarea" :label="__('Description')" />
				<ErrorMessage :message="error" />
			</form>
		</template>
		<template #actions>
			<div class="flex justify-end gap-2">
				<Button variant="ghost" @click="open = false">{{ __("Cancel") }}</Button>
				<Button variant="solid" :loading="creating" @click="create">{{ __("Create") }}</Button>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue"
import { createResource, DatePicker } from "frappe-ui"
import UserPicker from "@/components/UserPicker.vue"
import { counts } from "@/data/hub"

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	defaults: { type: Object, default: () => ({}) },
})

const emit = defineEmits(["update:modelValue", "created"])

const open = computed({
	get: () => props.modelValue,
	set: (value) => emit("update:modelValue", value),
})

const error = ref("")
const creating = ref(false)

const form = reactive({
	subject: "",
	request_type: "Question",
	assign_to: "",
	due_date: "",
	description: "",
})

watch(open, (isOpen) => {
	if (isOpen) {
		error.value = ""
		form.subject = props.defaults.subject || ""
		form.request_type = props.defaults.request_type || "Question"
		form.assign_to = props.defaults.assign_to || ""
		form.due_date = props.defaults.due_date || ""
		form.description = props.defaults.description || ""
	}
})

const requestTypes = [
	{ label: __("Missing Justificative"), value: "Missing Justificative" },
	{ label: __("Question"), value: "Question" },
	{ label: __("Correction Needed"), value: "Correction Needed" },
	{ label: __("Information"), value: "Information" },
]

const requestCreator = createResource({
	url: "etransactions.etransactions_hub.api.create_request",
	method: "POST",
})

async function create() {
	if (!form.subject) {
		error.value = __("Subject is required")
		return
	}

	creating.value = true
	error.value = ""
	try {
		const name = await requestCreator.submit({
			subject: form.subject,
			request_type: form.request_type,
			description: form.description || null,
			due_date: form.due_date || null,
			assign_to: form.assign_to || null,
			inbox_item: props.defaults.inbox_item || null,
			reference_doctype: props.defaults.reference_doctype || null,
			reference_name: props.defaults.reference_name || null,
		})
		counts.reload()
		emit("created", name)
		open.value = false
	} catch (exception) {
		error.value = exception.messages?.join("\n") || exception.message
	} finally {
		creating.value = false
	}
}
</script>
