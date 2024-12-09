<script setup>
import { onMounted, onUpdated, ref, watch, computed } from "vue";

const props = defineProps(["df", "modelValue"]);
const emits = defineEmits(["update:modelValue", "rowChecked"]);
const vModel = computed({
	get() {
		return props.modelValue;
	},
	set(value) {
		emits("update:modelValue", value);
	}
});

const fieldObject = ref(null);
const fieldWrapper = ref(null);

const refreshInput = () => {
	if (!fieldWrapper.value) return;
	fieldWrapper.value.innerHTML = "";

	let df = { ...props.df };
	if (!df.read_only) {
		df.onchange = () => {
			if (fieldObject.value) {
				vModel.value = fieldObject.value.get_value();
			}
		};
	}

	if (!df.on_setup) {
		df.on_setup = (f) => {
			f.wrapper.on("click", ".grid-row-check", (e) => {
				const selected_rows = f.grid_rows.filter(r => r.doc.__checked)
				emits("rowChecked", selected_rows);
			})
		};
	}

	fieldObject.value = frappe.ui.form.make_control({
		df: df,
		parent: fieldWrapper.value,
		render_input: true,
		value: vModel.value
	});
};

onUpdated(refreshInput);
onMounted(refreshInput);
watch(
	() => [props.df, props.df?.label, props.df?.description, props.df?.reqd, props.df?.read_only, props.df?.data],
	refreshInput
);
watch(vModel, () => {
	fieldObject.value?.set_value(vModel.value);
});
</script>

<template>
	<div ref="fieldWrapper" />
</template>