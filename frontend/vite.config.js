import path from "node:path"
import vue from "@vitejs/plugin-vue"
import frappeui from "frappe-ui/vite"
import { defineConfig } from "vite"

// https://vitejs.dev/config/
export default defineConfig({
	plugins: [
		frappeui({
			frappeProxy: true,
			jinjaBootData: true,
			lucideIcons: true,
			buildConfig: {
				outDir: "../etransactions/public/ehub",
				indexHtmlPath: "../etransactions/www/ehub.html",
				emptyOutDir: true,
				sourcemap: true,
			},
		}),
		vue(),
	],
	build: {
		chunkSizeWarningLimit: 1500,
		outDir: "../etransactions/public/ehub",
		emptyOutDir: true,
		target: "es2021",
		sourcemap: true,
		commonjsOptions: {
			// Only the Tailwind config needs CJS interop; do NOT blanket-process
			// node_modules (that breaks ESM deps like @vuepic/vue-datepicker).
			include: [/tailwind.config.js/],
		},
	},
	resolve: {
		alias: {
			"@": path.resolve(__dirname, "src"),
			"tailwind.config.js": path.resolve(__dirname, "tailwind.config.js"),
		},
		// dokos-ui is linked locally with its own frappe-ui/vue/vue-router; force a
		// single shared instance so frappe-ui plugins (resourcesPlugin, setConfig) work
		// and dokos-ui's RouterLink-based components (BSidebarLink, BBackButton) inject
		// the same router as the app.
		dedupe: ["frappe-ui", "vue", "vue-router"],
	},
	optimizeDeps: {
		include: ["feather-icons", "tailwind.config.js"],
	},
	server: {
		allowedHosts: true,
	},
})
