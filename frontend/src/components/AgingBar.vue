<template>
	<div class="mt-3">
		<div class="flex h-2 w-full overflow-hidden rounded bg-gray-100">
			<div
				v-for="segment in segments"
				:key="segment.key"
				class="h-2"
				:class="segment.color"
				:style="{ width: `${segment.pct}%` }"
				:title="`${segment.label}: ${money(segment.amount)}`"
			></div>
		</div>
		<dl class="mt-2 grid grid-cols-5 gap-1 text-center text-xs">
			<div v-for="segment in segments" :key="segment.key">
				<dt class="text-gray-500">{{ segment.label }}</dt>
				<dd class="text-gray-900">{{ money(segment.amount) }}</dd>
			</div>
		</dl>
	</div>
</template>

<script setup>
import { computed } from "vue"

const props = defineProps({
	buckets: { type: Object, required: true },
	currency: { type: String, default: "" },
})

const definition = [
	{ key: "current", label: __("Current"), color: "bg-green-500" },
	{ key: "d1_30", label: __("1–30"), color: "bg-yellow-400" },
	{ key: "d31_60", label: __("31–60"), color: "bg-orange-400" },
	{ key: "d61_90", label: __("61–90"), color: "bg-orange-600" },
	{ key: "d90_plus", label: __("90+"), color: "bg-red-600" },
]

const total = computed(() =>
	definition.reduce((sum, segment) => sum + Number(props.buckets[segment.key] || 0), 0)
)

const segments = computed(() =>
	definition.map((segment) => {
		const amount = Number(props.buckets[segment.key] || 0)
		return {
			...segment,
			amount,
			pct: total.value ? (amount / total.value) * 100 : 0,
		}
	})
)

function money(amount) {
	const value = Number(amount || 0)
	if (!props.currency) {
		return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(value)
	}
	return new Intl.NumberFormat(undefined, {
		style: "currency",
		currency: props.currency,
		maximumFractionDigits: 0,
	}).format(value)
}
</script>
