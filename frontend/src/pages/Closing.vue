<template>
	<BPage>
		<div class="mx-auto w-full max-w-3xl">
		<div class="mb-4 flex items-center justify-between">
			<h1 class="flex items-center gap-2 text-lg font-semibold text-gray-900">
				<ClipboardCheck class="h-5 w-5 text-brand-600" aria-hidden="true" />
				{{ __("Period Closing") }}
			</h1>
			<Button v-if="canManageTemplates" variant="ghost" @click="templateDialogOpen = true">
				{{ __("Manage templates") }}
			</Button>
		</div>

		<p v-if="metaError" class="mb-3 rounded bg-amber-50 px-3 py-2 text-sm text-amber-800" aria-live="polite">
			{{ __("Could not load your permissions, management actions may be unavailable: {0}", [metaError]) }}
		</p>

		<template v-if="period">
			<div class="mb-4 rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
				<div class="flex items-center justify-between">
					<h2 class="text-base font-semibold text-gray-900">{{ period.title }}</h2>
					<div class="flex items-center gap-2">
						<Badge :theme="period.status === 'Completed' ? 'green' : 'orange'" variant="subtle">
							{{ __(period.status) }}
						</Badge>
						<Button v-if="canManagePeriods" size="sm" variant="ghost" @click="editPeriod">
							{{ __("Edit dates") }}
						</Button>
						<Button
							v-if="canManagePeriods"
							size="sm"
							variant="ghost"
							theme="red"
							:loading="deleting"
							@click="deletePeriod"
						>
							{{ __("Delete") }}
						</Button>
					</div>
				</div>
				<div class="mt-3" role="progressbar" :aria-valuenow="Math.round(period.progress)" aria-valuemin="0" aria-valuemax="100" :aria-label="__('Closing progress')">
					<div class="h-2 w-full rounded bg-gray-100">
						<div
							class="h-2 rounded"
							:class="period.status === 'Completed' ? 'bg-green-600' : 'bg-brand-500'"
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

			<div class="mb-2 flex items-center justify-between">
				<h3 class="text-sm font-semibold text-gray-700">{{ __("Tasks") }}</h3>
				<Button v-if="canManagePeriods" size="sm" variant="subtle" @click="addTask">
					{{ __("Add task") }}
				</Button>
			</div>

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
					<div class="flex flex-shrink-0 items-center gap-2">
						<div class="w-44">
							<FormControl
								:modelValue="task.status"
								type="select"
								:label="__('Status of {0}', [task.subject])"
								:options="taskStatuses"
								@update:modelValue="(value) => updateStatus(task, value)"
							/>
						</div>
						<Button
							size="sm"
							variant="ghost"
							icon="message-square"
							:label="__('Raise request for {0}', [task.subject])"
							@click="raiseRequest(task)"
						/>
						<Button
							v-if="canManagePeriods"
							size="sm"
							variant="ghost"
							icon="edit-2"
							:label="__('Edit {0}', [task.subject])"
							@click="editTask(task)"
						/>
						<Button
							v-if="canManagePeriods"
							size="sm"
							variant="ghost"
							theme="red"
							icon="trash-2"
							:label="__('Delete {0}', [task.subject])"
							@click="deleteTask(task)"
						/>
					</div>
				</li>
			</ul>
		</template>
		<div v-else class="rounded border border-dashed border-gray-300 bg-white p-6 text-center">
			<p class="text-sm text-gray-600">{{ __("No closing period in progress.") }}</p>
			<Button
				v-if="canManagePeriods"
				class="mt-3"
				variant="solid"
				@click="startPeriod"
			>
				{{ __("Start a closing period") }}
			</Button>
		</div>

		<ClosingPeriodDialog v-model="periodDialogOpen" :period="periodToEdit" @saved="onPeriodSaved" />
		<ClosingTaskDialog v-model="taskDialogOpen" :period="period?.name" :task="taskToEdit" @saved="onTaskSaved" />
		<ChecklistTemplateDialog v-model="templateDialogOpen" @saved="onTemplateSaved" />
		</div>
	</BPage>
</template>

<script setup>
import { computed, ref } from "vue"
import { createListResource, createResource } from "frappe-ui"
import { ClipboardCheck } from "lucide-vue-next"
import ClosingPeriodDialog from "@/components/ClosingPeriodDialog.vue"
import ClosingTaskDialog from "@/components/ClosingTaskDialog.vue"
import ChecklistTemplateDialog from "@/components/ChecklistTemplateDialog.vue"
import { closingMeta, counts, runDocMethod } from "@/data/hub"

const feedback = ref("")
const deleting = ref(false)
const periodDialogOpen = ref(false)
const taskDialogOpen = ref(false)
const templateDialogOpen = ref(false)
const periodToEdit = ref(null)
const taskToEdit = ref(null)

const period = computed(() => counts.data?.closing || null)

// Fail open: show management actions unless the server has explicitly said the
// user lacks the permission. The backend re-checks permissions on every write,
// so an over-shown control surfaces a clear error instead of silently vanishing
// when the closingMeta resource is slow, errored or not yet loaded.
const canManagePeriods = computed(() => closingMeta.data?.can_manage_periods ?? true)
const canManageTemplates = computed(() => closingMeta.data?.can_manage_templates ?? true)
const metaError = computed(() => {
	const error = closingMeta.error
	if (!error) return ""
	const raw = error.messages?.join("\n") || error.message || ""
	// A non-JSON body (login page, 404, server error page) surfaces as a
	// "Unexpected token '<'" JSON.parse error. Show an actionable message
	// instead of leaking the parser internals to the accountant.
	if (/Unexpected token '<'|<!DOCTYPE|is not valid JSON/i.test(raw)) {
		return __("Please reload the page or sign in again.")
	}
	return raw
})

const tasks = createListResource({
	doctype: "Closing Task",
	fields: ["name", "subject", "status", "due_date", "description", "route"],
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

const periodDeleter = createResource({
	url: "etransactions.etransactions_hub.api.delete_closing_period",
	method: "POST",
})

const taskDeleter = createResource({
	url: "frappe.client.delete",
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

function startPeriod() {
	periodToEdit.value = null
	periodDialogOpen.value = true
}

function editPeriod() {
	periodToEdit.value = period.value
	periodDialogOpen.value = true
}

function onPeriodSaved() {
	feedback.value = __("Closing period saved.")
	counts.reload()
	tasks.reload()
}

function addTask() {
	taskToEdit.value = null
	taskDialogOpen.value = true
}

function editTask(task) {
	taskToEdit.value = task
	taskDialogOpen.value = true
}

function onTaskSaved() {
	feedback.value = __("Task saved.")
	tasks.reload()
	counts.reload()
}

async function deleteTask(task) {
	if (!window.confirm(__("Delete this task?"))) {
		return
	}
	try {
		await taskDeleter.submit({ doctype: "Closing Task", name: task.name })
		feedback.value = __("Task deleted.")
		tasks.reload()
		counts.reload()
	} catch (exception) {
		feedback.value = exception.messages?.join("\n") || exception.message
	}
}

async function raiseRequest(task) {
	try {
		await runDocMethod("Closing Task", task.name, "create_request")
		feedback.value = __("Request created for {0}.", [task.subject])
		counts.reload()
	} catch (exception) {
		feedback.value = exception.messages?.join("\n") || exception.message
	}
}

function onTemplateSaved() {
	feedback.value = __("Checklist template saved.")
}

async function deletePeriod() {
	if (!window.confirm(__("Delete this closing period and all its tasks?"))) {
		return
	}
	deleting.value = true
	try {
		await periodDeleter.submit({ name: period.value.name })
		feedback.value = __("Closing period deleted.")
		counts.reload()
	} catch (exception) {
		feedback.value = exception.messages?.join("\n") || exception.message
	} finally {
		deleting.value = false
	}
}
</script>
