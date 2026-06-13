<template>
	<Autocomplete
		:label="label"
		:options="options"
		:modelValue="selectedOption"
		:placeholder="placeholder || __('Nobody yet')"
		@change="(option) => emit('update:modelValue', option?.value || '')"
	>
		<template #prefix>
			<Avatar
				v-if="selectedOption"
				:label="selectedOption.label"
				:image="selectedOption.image"
				size="sm"
				class="mr-2"
			/>
		</template>
		<template #item-prefix="{ option }">
			<Avatar :label="option.label" :image="option.image" size="sm" />
		</template>
	</Autocomplete>
</template>

<script setup>
import { computed } from "vue"
import { Autocomplete, Avatar } from "frappe-ui"
import { assignableUsers } from "@/data/hub"

const props = defineProps({
	modelValue: { type: String, default: "" },
	label: { type: String, default: "" },
	placeholder: { type: String, default: "" },
})

const emit = defineEmits(["update:modelValue"])

const options = computed(() =>
	(assignableUsers.data || []).map((user) => ({
		label: user.full_name || user.name,
		value: user.name,
		image: user.user_image,
	}))
)

const selectedOption = computed(
	() => options.value.find((option) => option.value === props.modelValue) || null
)
</script>
