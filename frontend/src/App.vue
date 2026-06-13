<script setup>
// eTransactions Hub shell wired to the dokos-ui BLayout sidebar/topbar slots.
// The visible chrome (left sidebar + topbar) is provided here and rendered by
// each page's <BPage> (which mounts a BLayout); the sidebar collapses to a
// bottom tab bar on mobile via dokos-ui's BLayout CSS.
import { provideNavContents, provideTopBarContents } from "dokos-ui"
import EhubSidebar from "@/components/EhubSidebar.vue"
import EhubTopBar from "@/components/EhubTopBar.vue"

provideNavContents(EhubSidebar)
provideTopBarContents(EhubTopBar)
</script>

<template>
	<router-view />
</template>
