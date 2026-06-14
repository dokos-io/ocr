<template>
	<Dialog v-model="open" :options="{ title: __('Manage Checklist Templates'), size: '4xl' }">
		<template #body-content>
			<div class="space-y-4">
				<div class="flex items-end gap-2">
					<div class="w-64 space-y-1.5">
						<label class="block text-xs text-gray-600">{{ __("Template") }}</label>
						<Autocomplete
							:options="templateOptions"
							:modelValue="selectedTemplateOption"
							:placeholder="__('Select a template')"
							@change="(option) => loadTemplate(option?.value)"
						/>
					</div>
					<Button @click="newTemplate">{{ __("New Template") }}</Button>
				</div>

				<form v-if="editing" class="space-y-4" @submit.prevent="save">
					<div class="grid grid-cols-3 gap-3">
						<FormControl
							v-model="form.template_name"
							type="text"
							:label="__('Template Name')"
							required
						/>
						<FormControl
							v-model="form.frequency"
							type="select"
							:label="__('Frequency')"
							:options="frequencyOptions"
						/>
						<LinkField
							doctype="Company"
							:modelValue="form.company"
							:label="__('Company')"
							:placeholder="__('None')"
							@update:modelValue="(value) => (form.company = value)"
						/>
					</div>

					<div>
						<div class="mb-1 flex items-center justify-between">
							<h3 class="text-sm font-medium text-gray-700">{{ __("Tasks") }}</h3>
							<Button size="sm" @click="addItem">{{ __("Add task") }}</Button>
						</div>
						<table class="w-full text-sm">
							<thead>
								<tr class="text-left text-xs text-gray-500">
									<th class="px-1 py-1">{{ __("Task Subject") }}</th>
									<th class="px-1 py-1">{{ __("Default Assignee") }}</th>
									<th class="w-20 px-1 py-1">{{ __("Day Offset") }}</th>
									<th class="px-1 py-1">{{ __("Route") }}</th>
									<th class="w-8"></th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="(item, index) in form.items" :key="index" class="align-top">
									<td class="px-1 py-1">
										<FormControl v-model="item.task_subject" type="text" />
									</td>
									<td class="px-1 py-1">
										<UserPicker v-model="item.default_assignee" />
									</td>
									<td class="px-1 py-1">
										<FormControl v-model.number="item.day_offset" type="number" />
									</td>
									<td class="px-1 py-1">
										<FormControl v-model="item.route" type="text" />
									</td>
									<td class="px-1 py-1">
										<Button variant="ghost" size="sm" icon="trash-2" :label="__('Remove task')" @click="removeItem(index)" />
									</td>
								</tr>
								<tr v-if="!form.items.length">
									<td colspan="5" class="px-1 py-2 text-xs text-gray-500">
										{{ __("No task yet. Add one.") }}
									</td>
								</tr>
							</tbody>
						</table>
					</div>

					<ErrorMessage :message="error" />
				</form>
			</div>
		</template>
		<template #actions>
			<div class="flex justify-end gap-2">
				<Button variant="ghost" @click="open = false">{{ __("Close") }}</Button>
				<Button v-if="editing" variant="solid" :loading="saving" @click="save">
					{{ __("Save Template") }}
				</Button>
			</div>
		</template>
	</Dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue"
import { Autocomplete, createResource } from "frappe-ui"
import UserPicker from "@/components/UserPicker.vue"
import LinkField from "@/components/LinkField.vue"
import { closingMeta } from "@/data/hub"

const props = defineProps({
	modelValue: { type: Boolean, default: false },
})

const emit = defineEmits(["update:modelValue", "saved"])

const open = computed({
	get: () => props.modelValue,
	set: (value) => emit("update:modelValue", value),
})

const editing = ref(false)
const error = ref("")
const saving = ref(false)

const form = reactive({
	name: "",
	template_name: "",
	frequency: "Monthly",
	company: "",
	items: [],
})

const frequencyOptions = [
	{ label: __("Monthly"), value: "Monthly" },
	{ label: __("Quarterly"), value: "Quarterly" },
	{ label: __("Yearly"), value: "Yearly" },
]

watch(open, (isOpen) => {
	if (isOpen) {
		editing.value = false
		error.value = ""
	}
})

const templateOptions = computed(() =>
	(closingMeta.data?.templates || []).map((template) => ({
		label: template.template_name,
		value: template.name,
	}))
)

const selectedTemplateOption = computed(
	() => templateOptions.value.find((option) => option.value === form.name) || null
)

const loader = createResource({
	url: "etransactions.etransactions_hub.api.get_checklist_template",
	method: "GET",
})

const saver = createResource({
	url: "etransactions.etransactions_hub.api.save_checklist_template",
	method: "POST",
})

function newTemplate() {
	Object.assign(form, { name: "", template_name: "", frequency: "Monthly", company: "", items: [] })
	error.value = ""
	editing.value = true
}

async function loadTemplate(name) {
	if (!name) return
	error.value = ""
	const data = await loader.submit({ name })
	Object.assign(form, {
		name: data.name,
		template_name: data.template_name,
		frequency: data.frequency || "Monthly",
		company: data.company || "",
		items: (data.items || []).map((item) => ({
			task_subject: item.task_subject,
			default_assignee: item.default_assignee || "",
			day_offset: item.day_offset || 0,
			description: item.description || "",
			route: item.route || "",
		})),
	})
	editing.value = true
}

function addItem() {
	form.items.push({ task_subject: "", default_assignee: "", day_offset: 0, description: "", route: "" })
}

function removeItem(index) {
	form.items.splice(index, 1)
}

async function save() {
	error.value = ""
	if (!form.template_name) {
		error.value = __("Template name is required")
		return
	}
	if (!form.items.length) {
		error.value = __("Add at least one task")
		return
	}

	saving.value = true
	try {
		const name = await saver.submit({
			template: JSON.stringify({
				name: form.name || undefined,
				template_name: form.template_name,
				frequency: form.frequency,
				company: form.company || null,
				items: form.items,
			}),
		})
		form.name = name
		await closingMeta.reload()
		emit("saved", name)
	} catch (exception) {
		error.value = exception.messages?.join("\n") || exception.message
	} finally {
		saving.value = false
	}
}
</script>
