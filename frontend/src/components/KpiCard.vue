<template>
	<component
		:is="to ? 'router-link' : href ? 'a' : 'div'"
		:to="to || undefined"
		:href="href || undefined"
		:target="href ? '_blank' : undefined"
		:rel="href ? 'noopener' : undefined"
		class="flex flex-col rounded-xl bg-white p-5 shadow-sm ring-1 ring-inset ring-gray-200"
		:class="clickable ? 'transition duration-150 hover:-translate-y-0.5 hover:shadow-md hover:ring-gray-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500' : ''"
	>
		<div class="flex items-start justify-between gap-3">
			<p class="min-w-0 text-xs font-medium uppercase tracking-wide text-gray-500">{{ title }}</p>
			<div
				v-if="icon"
				class="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg"
				:class="iconWrapClass"
			>
				<component :is="icon" class="h-5 w-5" aria-hidden="true" />
			</div>
		</div>
		<p class="mt-3 text-3xl font-semibold tracking-tight" :class="valueClass">{{ value }}</p>
		<p v-if="sublabel" class="mt-1 truncate text-xs text-gray-600">{{ sublabel }}</p>
		<slot />
	</component>
</template>

<script setup>
import { computed } from "vue"

const props = defineProps({
	title: { type: String, required: true },
	value: { type: [String, Number], default: "—" },
	sublabel: { type: String, default: "" },
	to: { type: [String, Object], default: null },
	href: { type: String, default: null },
	icon: { type: [Object, Function], default: null },
	theme: { type: String, default: "brand" },
})

const clickable = computed(() => !!props.to || !!props.href)

const iconWrapClass = computed(
	() =>
		({
			brand: "bg-brand-50 text-brand-600",
			success: "bg-green-50 text-green-600",
			warning: "bg-orange-50 text-orange-600",
			danger: "bg-red-50 text-red-600",
			default: "bg-gray-100 text-gray-600",
		})[props.theme] || "bg-brand-50 text-brand-600"
)

const valueClass = computed(
	() =>
		({
			brand: "text-gray-900",
			default: "text-gray-900",
			danger: "text-red-600",
			warning: "text-orange-600",
			success: "text-green-600",
		})[props.theme] || "text-gray-900"
)
</script>
