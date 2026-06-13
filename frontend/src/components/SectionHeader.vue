<template>
	<div class="mb-3 flex items-center gap-2">
		<component v-if="icon" :is="icon" class="h-4 w-4 text-brand-600" aria-hidden="true" />
		<h2 class="text-sm font-semibold text-gray-800">{{ title }}</h2>
	</div>
</template>

<script setup>
defineProps({
	title: { type: String, required: true },
	icon: { type: [Object, Function], default: null },
})
</script>
