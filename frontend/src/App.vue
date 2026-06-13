<template>
	<div class="flex h-full flex-col">
		<header class="flex items-center justify-between border-b border-gray-200 bg-white px-5 py-3 shadow-sm">
			<div class="flex items-center gap-6">
				<img :src="logo" :alt="__('eTransactions Hub')" class="h-7 w-auto" />
				<nav :aria-label="__('Main navigation')" class="flex gap-1">
					<router-link
						v-for="tab in tabs"
						:key="tab.route"
						:to="tab.route"
						class="flex items-center gap-2 rounded-md px-3 py-1.5 text-sm font-medium text-gray-600 transition-colors hover:bg-gray-100 hover:text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
						:class="{ 'bg-brand-50 text-brand-700 hover:bg-brand-50': isActive(tab.route) }"
						:aria-current="isActive(tab.route) ? 'page' : undefined"
					>
						{{ tab.label }}
						<Badge v-if="tab.badge" theme="orange" variant="subtle">{{ tab.badge }}</Badge>
					</router-link>
				</nav>
			</div>
		</header>
		<main class="flex-1 overflow-hidden bg-gray-50">
			<router-view />
		</main>
	</div>
</template>

<script setup>
import { computed } from "vue"
import { useRoute } from "vue-router"
import { counts } from "@/data/hub"
import logo from "@/assets/etransactions-logo.svg"

const route = useRoute()

const tabs = computed(() => {
	const data = counts.data || {}
	return [
		{ route: "/", label: __("Overview") },
		{ route: "/inbox", label: __("Inbox"), badge: data.inbox_to_triage || 0 },
		{ route: "/requests", label: __("Requests"), badge: data.waiting_on_me || 0 },
		{
			route: "/closing",
			label: __("Closing"),
			badge: data.closing ? `${Math.round(data.closing.progress)}%` : null,
		},
	]
})

function isActive(path) {
	return route.path === path
}
</script>
