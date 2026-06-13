<template>
	<Dialog v-model="open" :options="{ title: isEdit ? __('Edit Task') : __('Add Task') }">
		<template #body-content>
			<form class="space-y-4" @submit.prevent="save">
				<FormControl
					v-model="form.subject"
					type="text"
					:label="__('Subject')"
					required
					autocomplete="off"
				/>
				<div class="space-y-1.5">
					<label class="block text-xs text-gray-600">{{ __("Due Date") }}</label>
					<DatePicker
						:modelValue="form.due_date"
						:placeholder="__('Select date')"
						@update:modelValue="(value) => (form.due_date = value)"
					/>
				</div>
				<FormControl v-model="form.description" type="textarea" :label="__('Description')" />
				<FormControl
					v-model="form.route"
					type="text"
					:label="__('Tool route')"
					:placeholder="__('e.g. /app/bank-reconciliation-tool')"
					autocomplete="off"
				/>
				<ErrorMessage :message="error" />
			</form>
		</template>
		<template #actions>
			<div class="flex justify-end gap-2">
				<Button variant="ghost" @click="open = false">{{ __("Cancel") }}</Button>
				<Button variant="solid" :loading="saving" @click="save">
					{{ isEdit ? __("Save") : __("Add") }}
				</Button>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue"
import { createResource, DatePicker } from "frappe-ui"

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	period: { type: String, default: "" },
	task: { type: Object, default: null },
})

const emit = defineEmits(["update:modelValue", "saved"])

const open = computed({
	get: () => props.modelValue,
	set: (value) => emit("update:modelValue", value),
})

const isEdit = computed(() => !!props.task?.name)
const error = ref("")
const saving = ref(false)

const form = reactive({
	subject: "",
	due_date: "",
	description: "",
	route: "",
})

watch(open, (isOpen) => {
	if (isOpen) {
		error.value = ""
		form.subject = props.task?.subject || ""
		form.due_date = props.task?.due_date || ""
		form.description = props.task?.description || ""
		form.route = props.task?.route || ""
	}
})

const inserter = createResource({
	url: "frappe.client.insert",
	method: "POST",
})

const setter = createResource({
	url: "frappe.client.set_value",
	method: "POST",
})

async function save() {
	error.value = ""
	if (!form.subject) {
		error.value = __("Subject is required")
		return
	}

	saving.value = true
	try {
		if (isEdit.value) {
			await setter.submit({
				doctype: "Closing Task",
				name: props.task.name,
				fieldname: {
					subject: form.subject,
					due_date: form.due_date || null,
					description: form.description || null,
					route: form.route || null,
				},
			})
		} else {
			await inserter.submit({
				doc: {
					doctype: "Closing Task",
					closing_period: props.period,
					subject: form.subject,
					due_date: form.due_date || null,
					description: form.description || null,
					route: form.route || null,
				},
			})
		}
		emit("saved")
		open.value = false
	} catch (exception) {
		error.value = exception.messages?.join("\n") || exception.message
	} finally {
		saving.value = false
	}
}
</script>
