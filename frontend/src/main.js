import { createApp } from "vue"

import App from "./App.vue"
import router from "./router"
import translationPlugin from "./translation"

import {
	Alert,
	Badge,
	Button,
	Dialog,
	ErrorMessage,
	FormControl,
	Input,
	TextInput,
	frappeRequest,
	pageMetaPlugin,
	resourcesPlugin,
	setConfig,
} from "frappe-ui"

import "./index.css"

const globalComponents = {
	Button,
	TextInput,
	Input,
	FormControl,
	ErrorMessage,
	Dialog,
	Alert,
	Badge,
}

const app = createApp(App)

setConfig("resourceFetcher", frappeRequest)

app.use(router)
app.use(resourcesPlugin)
app.use(pageMetaPlugin)
app.use(translationPlugin)

for (const key in globalComponents) {
	app.component(key, globalComponents[key])
}

app.mount("#app")
