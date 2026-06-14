<template>
	<Autocomplete
		:label="label"
		:options="options"
		:modelValue="selectedOption"
		:placeholder="placeholder || __('Select {0}', [doctype])"
		@change="(option) => emit('update:modelValue', option?.value || '')"
	/>
</template>

<script setup>
import { computed } from "vue"
import { Autocomplete, createListResource } from "frappe-ui"

const props = defineProps({
	doctype: { type: String, required: true },
	modelValue: { type: String, default: "" },
	label: { type: String, default: "" },
	placeholder: { type: String, default: "" },
	filters: { type: Object, default: () => ({}) },
})

const emit = defineEmits(["update:modelValue"])

const records = createListResource({
	doctype: props.doctype,
	fields: ["name"],
	filters: props.filters,
	pageLength: 100,
	auto: true,
})

const options = computed(() =>
	(records.data || []).map((record) => ({ label: record.name, value: record.name }))
)

const selectedOption = computed(
	() => options.value.find((option) => option.value === props.modelValue) || null
)
</script>
