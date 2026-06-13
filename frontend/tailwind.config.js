import frappeUIPreset from "frappe-ui/tailwind"

// dokos-ui components rely on frappe-ui's design tokens (via its Tailwind preset)
// plus a few spacing extras. We use frappe-ui's preset directly and add dokos-ui's
// content globs + extras so its components are styled.
export default {
	presets: [frappeUIPreset.default || frappeUIPreset],
	content: [
		"./index.html",
		"./src/**/*.{vue,js,ts,jsx,tsx}",
		"./node_modules/frappe-ui/src/components/**/*.{vue,js,ts,jsx,tsx}",
		"./node_modules/dokos-ui/src/**/*.{vue,js,ts,jsx,tsx}",
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
			height: { 18: "68px" },
			margin: { 3.5: "14px" },
			padding: { 2.5: "10px", 3.5: "14px" },
			screens: {
				standalone: { raw: "(display-mode: standalone)" },
			},
		},
	},
	plugins: [],
}
