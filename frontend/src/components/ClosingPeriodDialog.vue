<template>
	<Dialog v-model="open" :options="{ title: isEdit ? __('Edit Closing Period') : __('Start a Closing Period') }">
		<template #body-content>
			<form class="space-y-4" @submit.prevent="save">
				<div v-if="!isEdit" class="space-y-1.5">
					<label class="block text-xs text-gray-600">{{ __("Checklist Template") }}</label>
					<Autocomplete
						:options="templateOptions"
						:modelValue="selectedTemplate"
						:placeholder="__('Select a template')"
						@change="(option) => (form.checklist_template = option?.value || '')"
					/>
				</div>
				<div class="space-y-1.5">
					<label class="block text-xs text-gray-600">{{ __("Period Start") }}</label>
					<DatePicker
						:modelValue="form.period_start"
						:placeholder="__('Select date')"
						@update:modelValue="(value) => (form.period_start = value)"
					/>
				</div>
				<div class="space-y-1.5">
					<label class="block text-xs text-gray-600">{{ __("Period End") }}</label>
					<DatePicker
						:modelValue="form.period_end"
						:placeholder="__('Select date')"
						@update:modelValue="(value) => (form.period_end = value)"
					/>
				</div>
				<ErrorMessage :message="error" />
			</form>
		</template>
		<template #actions>
			<div class="flex justify-end gap-2">
				<Button variant="ghost" @click="open = false">{{ __("Cancel") }}</Button>
				<Button variant="solid" :loading="saving" @click="save">
					{{ isEdit ? __("Save") : __("Start") }}
				</Button>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue"
import { Autocomplete, createResource, DatePicker } from "frappe-ui"
import { closingMeta } from "@/data/hub"

const props = defineProps({
	modelValue: { type: Boolean, default: false },
	period: { type: Object, default: null },
})

const emit = defineEmits(["update:modelValue", "saved"])

const open = computed({
	get: () => props.modelValue,
	set: (value) => emit("update:modelValue", value),
})

const isEdit = computed(() => !!props.period?.name)
const error = ref("")
const saving = ref(false)

const form = reactive({
	checklist_template: "",
	period_start: "",
	period_end: "",
})

watch(open, (isOpen) => {
	if (isOpen) {
		error.value = ""
		form.checklist_template = ""
		form.period_start = props.period?.period_start || ""
		form.period_end = props.period?.period_end || ""
	}
})

const templateOptions = computed(() =>
	(closingMeta.data?.templates || []).map((template) => ({
		label: template.template_name,
		value: template.name,
	}))
)

const selectedTemplate = computed(
	() => templateOptions.value.find((option) => option.value === form.checklist_template) || null
)

const creator = createResource({
	url: "etransactions.etransactions_hub.doctype.closing_period.closing_period.create_period_from_template",
	method: "POST",
})

const updater = createResource({
	url: "etransactions.etransactions_hub.api.update_closing_period",
	method: "POST",
})

async function save() {
	error.value = ""
	if (!isEdit.value && !form.checklist_template) {
		error.value = __("Please select a checklist template")
		return
	}
	if (!form.period_start || !form.period_end) {
		error.value = __("Please set the period start and end dates")
		return
	}

	saving.value = true
	try {
		let name
		if (isEdit.value) {
			name = await updater.submit({
				name: props.period.name,
				period_start: form.period_start,
				period_end: form.period_end,
			})
		} else {
			name = await creator.submit({
				checklist_template: form.checklist_template,
				period_start: form.period_start,
				period_end: form.period_end,
			})
		}
		emit("saved", name)
		open.value = false
	} catch (exception) {
		error.value = exception.messages?.join("\n") || exception.message
	} finally {
		saving.value = false
	}
}
</script>
