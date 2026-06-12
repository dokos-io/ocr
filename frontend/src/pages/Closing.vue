<template>
	<div class="mx-auto max-w-3xl p-6">
		<template v-if="period">
			<div class="mb-4 rounded border border-gray-200 bg-white p-4">
				<div class="flex items-center justify-between">
					<h2 class="text-base font-semibold text-gray-900">{{ period.title }}</h2>
					<Badge :theme="period.status === 'Completed' ? 'green' : 'orange'" variant="subtle">
						{{ __(period.status) }}
					</Badge>
				</div>
				<div class="mt-3" role="progressbar" :aria-valuenow="Math.round(period.progress)" aria-valuemin="0" aria-valuemax="100" :aria-label="__('Closing progress')">
					<div class="h-2 w-full rounded bg-gray-100">
						<div
							class="h-2 rounded bg-green-600"
							:style="{ width: `${period.progress}%` }"
						></div>
					</div>
					<p class="mt-1 text-sm text-gray-600">
						{{ __("{0}% complete", [Math.round(period.progress)]) }}
					</p>
				</div>
			</div>

			<p v-if="feedback" class="mb-3 rounded bg-green-50 px-3 py-2 text-sm text-green-800" aria-live="polite">
				{{ feedback }}
			</p>

			<ul role="list" class="space-y-2">
				<li
					v-for="task in tasks.data || []"
					:key="task.name"
					class="flex items-center justify-between gap-3 rounded border border-gray-200 bg-white px-3 py-2"
				>
					<div class="min-w-0">
						<p class="truncate text-sm font-medium text-gray-900">{{ task.subject }}</p>
						<p class="text-xs text-gray-600">
							<template v-if="task.due_date">{{ __("Due {0}", [task.due_date]) }}</template>
						</p>
					</div>
					<div class="w-44 flex-shrink-0">
						<FormControl
							:modelValue="task.status"
							type="select"
							:label="__('Status of {0}', [task.subject])"
							:options="taskStatuses"
							@update:modelValue="(value) => updateStatus(task, value)"
						/>
					</div>
				</li>
			</ul>
		</template>
		<p v-else class="text-sm text-gray-600">
			{{ __("No closing period in progress. Start one from the desk (Closing Period).") }}
		</p>
	</div>
</template>

<script setup>
import { computed, ref } from "vue"
import { createListResource, createResource } from "frappe-ui"
import { counts } from "@/data/hub"

const feedback = ref("")

const period = computed(() => counts.data?.closing || null)

const tasks = createListResource({
	doctype: "Closing Task",
	fields: ["name", "subject", "status", "due_date", "route"],
	filters: computed(() => [["closing_period", "=", period.value?.name || ""]]),
	orderBy: "due_date asc",
	pageLength: 100,
	auto: true,
})

const taskStatuses = [
	{ label: __("Pending"), value: "Pending" },
	{ label: __("In Progress"), value: "In Progress" },
	{ label: __("Blocked"), value: "Blocked" },
	{ label: __("Done"), value: "Done" },
	{ label: __("Not Applicable"), value: "Not Applicable" },
]

const statusSetter = createResource({
	url: "frappe.client.set_value",
	method: "POST",
})

async function updateStatus(task, value) {
	try {
		await statusSetter.submit({
			doctype: "Closing Task",
			name: task.name,
			fieldname: "status",
			value,
		})
		feedback.value = __("Task updated.")
		tasks.reload()
		counts.reload()
	} catch (exception) {
		feedback.value = exception.messages?.join("\n") || exception.message
	}
}
</script>
