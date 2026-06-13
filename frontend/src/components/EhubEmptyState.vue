<script setup>
// eTransactions Hub empty-state wrapper: dokos-ui BEmptyList with a black title.
// BEmptyList renders its title in `text-primary`; overriding the colour on a
// child <span> keeps every empty state on a clean black title. Mirrors the
// cockpit app's CockpitEmptyState.
import { BEmptyList } from "dokos-ui"

defineProps({
	title: { type: String, default: "" },
	description: { type: String, default: "" },
	icon: { type: [String, Function], default: undefined },
})
</script>

<template>
	<BEmptyList :description="description" :icon="icon">
		<template #title>
			<span class="text-gray-900">{{ title }}</span>
		</template>
		<slot />
	</BEmptyList>
</template>
