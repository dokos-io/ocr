import frappeUIPreset from "frappe-ui/src/tailwind/preset"

export default {
	presets: [frappeUIPreset],
	content: [
		"./index.html",
		"./src/**/*.{vue,js,ts,jsx,tsx}",
		"./node_modules/frappe-ui/src/components/**/*.{vue,js,ts,jsx,tsx}",
	],
	theme: {
		extend: {
			colors: {
				brand: {
					DEFAULT: "#024a70",
					50: "#eef5fa",
					100: "#d4e6f1",
					200: "#a9cce3",
					300: "#7db2d4",
					400: "#3d7ea8",
					500: "#024a70",
					600: "#023a5a",
					700: "#012c44",
				},
			},
		},
	},
	plugins: [],
}
