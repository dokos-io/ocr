<script setup>
// eTransactions Hub sidebar navigation (dokos-ui BLayout side slot).
import { computed } from "vue"
import { BSidebarLink } from "dokos-ui"
import { counts } from "@/data/hub"

const data = computed(() => counts.data || {})
const closingBadge = computed(() =>
	data.value.closing ? `${Math.round(data.value.closing.progress)}%` : null,
)
</script>

<template>
	<!-- Labels collapse to icons-only on mobile (the bottom tab bar); kept in the
	a11y tree via sr-only so screen readers still announce each destination. -->
	<BSidebarLink :to="{ name: 'Overview' }" icon="layout-dashboard">
		<span class="max-md:sr-only">{{ __("Overview") }}</span>
	</BSidebarLink>
	<BSidebarLink :to="{ name: 'Inbox' }" icon="inbox" :badge="data.inbox_to_triage || null">
		<span class="max-md:sr-only">{{ __("Inbox") }}</span>
	</BSidebarLink>
	<BSidebarLink :to="{ name: 'Requests' }" icon="message-square" :badge="data.waiting_on_me || null">
		<span class="max-md:sr-only">{{ __("Requests") }}</span>
	</BSidebarLink>
	<BSidebarLink :to="{ name: 'Closing' }" icon="clipboard-check" :badge="closingBadge">
		<span class="max-md:sr-only">{{ __("Closing") }}</span>
	</BSidebarLink>
</template>
