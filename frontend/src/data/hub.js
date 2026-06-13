import { createResource } from "frappe-ui"

export const counts = createResource({
	url: "etransactions.etransactions_hub.api.get_counts",
	cache: "hub-counts",
	auto: true,
})

export const assignableUsers = createResource({
	url: "etransactions.etransactions_hub.api.get_assignable_users",
	cache: "hub-assignable-users",
	auto: true,
})

export const closingMeta = createResource({
	url: "etransactions.etransactions_hub.api.get_closing_meta",
	auto: true,
})

const docMethodRunner = createResource({
	url: "run_doc_method",
	method: "POST",
})

export function runDocMethod(doctype, name, method, args = {}) {
	return docMethodRunner.submit({
		dt: doctype,
		dn: name,
		method,
		args: JSON.stringify(args),
	})
}
