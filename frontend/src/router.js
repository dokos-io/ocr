import { createRouter, createWebHistory } from "vue-router"

const routes = [
	{
		path: "/",
		name: "Inbox",
		component: () => import("@/pages/Inbox.vue"),
	},
	{
		path: "/requests",
		name: "Requests",
		component: () => import("@/pages/Requests.vue"),
	},
	{
		path: "/closing",
		name: "Closing",
		component: () => import("@/pages/Closing.vue"),
	},
]

const router = createRouter({
	history: createWebHistory("/accounting-hub"),
	routes,
})

router.beforeEach((to, from, next) => {
	const cookies = new URLSearchParams(document.cookie.split("; ").join("&"))
	const user = cookies.get("user_id")
	if (!user || user === "Guest") {
		window.location.href = `/login?redirect-to=${encodeURIComponent("/accounting-hub" + to.fullPath)}`
		return
	}
	next()
})

export default router
