<script setup>
// eTransactions Hub compact empty-state placeholder. Replaces dokos-ui BEmptyList
// (whose 128px triple icon + 2rem title dwarfed section headings) with a small,
// contained figure that reads cleanly inside a section. Same props as before so
// every caller keeps working. Mirrors the cockpit app's CockpitEmptyState.
import { BIcon } from "dokos-ui"

defineProps({
	title: { type: String, default: "" },
	description: { type: String, default: "" },
	icon: { type: [String, Function], default: undefined },
})
</script>

<template>
	<div class="flex flex-col items-center justify-center gap-2 py-8 text-center">
		<BIcon v-if="icon" :name="icon" class="h-8 w-8 text-gray-400" />
		<p v-if="title" class="text-sm font-medium text-gray-900">{{ title }}</p>
		<p v-if="description" class="text-xs text-gray-500">{{ description }}</p>
		<slot />
	</div>
</template>
