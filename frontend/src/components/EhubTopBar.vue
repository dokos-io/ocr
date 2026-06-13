<script setup>
// eTransactions Hub topbar (dokos-ui BLayout top slot): logo + Desk escape hatch.
import { RouterLink } from "vue-router"
import { ExternalLink } from "lucide-vue-next"
import logo from "@/assets/etransactions-logo.svg"
</script>

<template>
	<RouterLink
		to="/"
		class="flex items-center gap-2 rounded focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-500"
	>
		<img :src="logo" :alt="__('eTransactions Hub')" class="h-7 w-auto" />
	</RouterLink>

	<div class="ml-auto flex items-center gap-3">
		<!-- Subtle global Desk escape hatch; desktop-only for now. -->
		<a
			href="/app"
			class="max-md:hidden flex h-7 w-7 items-center justify-center rounded text-gray-400 hover:bg-gray-100 hover:text-gray-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-gray-500"
		>
			<ExternalLink class="h-4 w-4" />
			<span class="sr-only">{{ __("Open Desk") }}</span>
		</a>
	</div>
</template>
