<template>
	<div class="h-full overflow-y-auto bg-gray-50">
		<div class="mx-auto max-w-6xl space-y-8 p-6">
			<div class="flex items-center justify-between gap-4">
				<h1 class="text-lg font-semibold text-gray-900">{{ __("Overview") }}</h1>
				<div class="w-64">
					<LinkField
						doctype="Company"
						:modelValue="selectedCompany"
						:label="__('Company')"
						@update:modelValue="onCompanyChange"
					/>
				</div>
			</div>

			<div v-if="data" class="space-y-8">
				<!-- Treasury -->
				<section v-if="data.treasury" :aria-label="__('Treasury')">
					<SectionHeader :icon="Wallet" :title="__('Treasury')" />
					<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
						<KpiCard
							:icon="Landmark"
							theme="brand"
							:title="__('Bank balance')"
							:value="money(data.treasury.bank_balance, data.treasury.currency)"
						/>
						<KpiCard
							:icon="RefreshCcw"
							:theme="data.treasury.unreconciled_count ? 'warning' : 'success'"
							:title="__('Unreconciled transactions')"
							:value="data.treasury.unreconciled_count"
							:sublabel="__('Open the reconciliation tool')"
							href="/app/bank-reconciliation-tool"
						/>
					</div>
				</section>

				<!-- Receivables & Payables -->
				<section v-if="data.receivables || data.payables" :aria-label="__('Receivables and payables')">
					<SectionHeader :icon="Scale" :title="__('Receivables & Payables')" />
					<div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
						<KpiCard
							v-if="data.receivables"
							:icon="ArrowDownLeft"
							theme="brand"
							:title="__('Receivables outstanding')"
							:value="money(data.receivables.total, currency)"
							href="/app/query-report/Accounts Receivable"
						>
							<AgingBar :buckets="data.receivables.buckets" :currency="currency" />
						</KpiCard>
						<KpiCard
							v-if="data.payables"
							:icon="ArrowUpRight"
							theme="brand"
							:title="__('Payables outstanding')"
							:value="money(data.payables.total, currency)"
							href="/app/query-report/Accounts Payable"
						>
							<AgingBar :buckets="data.payables.buckets" :currency="currency" />
						</KpiCard>
					</div>
				</section>

				<!-- Close readiness -->
				<section :aria-label="__('Close readiness')">
					<SectionHeader :icon="ClipboardCheck" :title="__('Close readiness')" />
					<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
						<KpiCard
							:icon="Gauge"
							theme="brand"
							:title="__('Closing progress')"
							:value="data.close.period ? `${Math.round(data.close.period.progress)}%` : __('No period')"
							:sublabel="data.close.period ? data.close.period.title : __('Start one in Closing')"
							to="/closing"
						/>
						<KpiCard
							:icon="FileWarning"
							:theme="data.data_quality.missing_justificative_open ? 'warning' : 'success'"
							:title="__('Missing justificatives')"
							:value="data.data_quality.missing_justificative_open"
							to="/requests"
						/>
						<KpiCard
							v-if="data.data_quality.supplier_invoices_low_confidence != null"
							:icon="AlertTriangle"
							:theme="data.data_quality.supplier_invoices_low_confidence ? 'warning' : 'success'"
							:title="__('Low-confidence invoices')"
							:value="data.data_quality.supplier_invoices_low_confidence"
						/>
						<KpiCard
							v-if="data.data_quality.customer_readiness_pct != null"
							:icon="ShieldCheck"
							theme="brand"
							:title="__('e-Invoicing readiness')"
							:value="`${data.data_quality.customer_readiness_pct}%`"
							:sublabel="
								data.data_quality.item_readiness_pct != null
									? __('Items {0}%', [data.data_quality.item_readiness_pct])
									: ''
							"
							href="/app/query-report/Customer eInvoice Readiness"
						/>
					</div>
				</section>

				<!-- Collaboration -->
				<section :aria-label="__('Collaboration')">
					<SectionHeader :icon="Users" :title="__('Collaboration')" />
					<div class="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
						<KpiCard
							:icon="UserCheck"
							:theme="data.collaboration.waiting_on_me ? 'warning' : 'default'"
							:title="__('Waiting on me')"
							:value="data.collaboration.waiting_on_me"
							to="/requests"
						/>
						<KpiCard
							:icon="Clock"
							:theme="data.collaboration.overdue ? 'danger' : 'success'"
							:title="__('Overdue requests')"
							:value="data.collaboration.overdue"
							to="/requests"
						/>
						<KpiCard
							:icon="Inbox"
							:theme="data.collaboration.inbox_to_triage ? 'warning' : 'success'"
							:title="__('Inbox to triage')"
							:value="data.collaboration.inbox_to_triage"
							to="/inbox"
						/>
					</div>
				</section>
			</div>

			<p v-else-if="overview.loading" class="text-sm text-gray-600">{{ __("Loading…") }}</p>
		</div>
	</div>
</template>

<script setup>
import { computed, ref, watch } from "vue"
import { createResource } from "frappe-ui"
import {
	AlertTriangle,
	ArrowDownLeft,
	ArrowUpRight,
	ClipboardCheck,
	Clock,
	FileWarning,
	Gauge,
	Inbox,
	Landmark,
	RefreshCcw,
	Scale,
	ShieldCheck,
	UserCheck,
	Users,
	Wallet,
} from "lucide-vue-next"
import KpiCard from "@/components/KpiCard.vue"
import AgingBar from "@/components/AgingBar.vue"
import LinkField from "@/components/LinkField.vue"
import SectionHeader from "@/components/SectionHeader.vue"

const selectedCompany = ref("")

const overview = createResource({
	url: "etransactions.etransactions_hub.api.get_overview",
	method: "GET",
	makeParams: () => ({ company: selectedCompany.value || null }),
	auto: true,
})

const data = computed(() => overview.data)
const currency = computed(() => overview.data?.treasury?.currency)

// Sync the selector with the company the backend resolved on first load.
watch(
	() => overview.data?.company,
	(company) => {
		if (company && !selectedCompany.value) {
			selectedCompany.value = company
		}
	}
)

function onCompanyChange(company) {
	selectedCompany.value = company
	overview.reload()
}

function money(amount, code) {
	const value = Number(amount || 0)
	if (!code) {
		return new Intl.NumberFormat(undefined, { maximumFractionDigits: 0 }).format(value)
	}
	return new Intl.NumberFormat(undefined, {
		style: "currency",
		currency: code,
		maximumFractionDigits: 0,
	}).format(value)
}
</script>
