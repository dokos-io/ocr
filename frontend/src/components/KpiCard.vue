<template>
	<component
		:is="to ? 'router-link' : href ? 'a' : 'div'"
		:to="to || undefined"
		:href="href || undefined"
		:target="href ? '_blank' : undefined"
		:rel="href ? 'noopener' : undefined"
		class="flex items-start gap-3 rounded-lg border border-l-4 border-gray-200 bg-white p-5"
		:class="[accentClass, clickable ? 'transition-shadow hover:shadow-md focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500' : '']"
	>
		<div
			v-if="icon"
			class="flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-lg"
			:class="iconWrapClass"
		>
			<component :is="icon" class="h-5 w-5" aria-hidden="true" />
		</div>
		<div class="min-w-0">
			<p class="text-xs font-medium uppercase tracking-wide text-gray-500">{{ title }}</p>
			<p class="mt-1 text-2xl font-semibold" :class="valueClass">{{ value }}</p>
			<p v-if="sublabel" class="mt-0.5 truncate text-xs text-gray-600">{{ sublabel }}</p>
			<slot />
		</div>
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

const accentClass = computed(
	() =>
		({
			brand: "border-l-brand-500",
			success: "border-l-green-500",
			warning: "border-l-orange-400",
			danger: "border-l-red-500",
			default: "border-l-gray-300",
		})[props.theme] || "border-l-brand-500"
)

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
