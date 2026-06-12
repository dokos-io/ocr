<template>
	<div class="flex h-full flex-col">
		<header class="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-2">
			<div class="flex items-center gap-6">
				<h1 class="text-lg font-semibold text-gray-900">{{ __("Accounting Hub") }}</h1>
				<nav :aria-label="__('Main navigation')" class="flex gap-1">
					<router-link
						v-for="tab in tabs"
						:key="tab.route"
						:to="tab.route"
						class="flex items-center gap-2 rounded px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-500"
						:class="{ 'bg-gray-100 text-gray-900': isActive(tab.route) }"
						:aria-current="isActive(tab.route) ? 'page' : undefined"
					>
						{{ tab.label }}
						<Badge v-if="tab.badge" theme="orange" variant="subtle">{{ tab.badge }}</Badge>
					</router-link>
				</nav>
			</div>
			<a
				href="/app"
				class="rounded px-2 py-1 text-sm text-gray-600 hover:text-gray-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-500"
			>
				{{ __("Open Desk") }}
			</a>
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

const route = useRoute()

const tabs = computed(() => {
	const data = counts.data || {}
	return [
		{ route: "/", label: __("Inbox"), badge: data.inbox_to_triage || 0 },
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
