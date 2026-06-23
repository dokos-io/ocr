// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt
//
// E-invoicing readiness indicator for master data (Customer / Supplier). The
// e-invoicing fields are edited natively in the eTransactions tab; this lean
// component renders a status pill plus a checklist of missing items at the top
// of that tab, each with a "Fix →" link that jumps to the field or related
// master that needs attention.

frappe.provide("etransactions");

etransactions.EinvoiceReadinessIndicator = class EinvoiceReadinessIndicator {
	constructor(frm) {
		this.frm = frm;
		this.party_type = frm.doctype; // "Customer" | "Supplier"
		this.findings = [];
	}

	get field() {
		return this.frm.fields_dict.etransactions_wizard_html;
	}

	refresh() {
		if (!this.field) return;
		this.render();
		this.load_readiness();
	}

	render() {
		const $w = $(this.field.wrapper).empty();
		this.$root = $(`
			<div class="et-readiness">
				<div class="et-readiness-pill"></div>
				<div class="et-readiness-body"></div>
			</div>
		`).appendTo($w);
		this.render_pill();
		this.render_body();
	}

	load_readiness() {
		if (this.frm.is_new()) {
			this.findings = [];
			this.render_pill();
			this.render_body();
			return;
		}
		frappe.call({
			method: "etransactions.plateforme_agreee.readiness.evaluate_party_readiness",
			args: { party_type: this.party_type, party: this.frm.doc.name },
			callback: (r) => {
				this.findings = r.message || [];
				this.render_pill();
				this.render_body();
			},
		});
	}

	readiness_state() {
		const f = this.findings || [];
		if (f.some((x) => x.severity === "error")) return ["red", __("Not ready to invoice")];
		if (f.some((x) => x.severity === "warning")) return ["orange", __("Almost ready")];
		return ["green", __("Ready to invoice")];
	}

	render_pill() {
		if (!this.$root) return;
		const [color, label] = this.readiness_state();
		this.$root.find(".et-readiness-pill").html(`<span class="indicator-pill ${color}">${label}</span>`);
	}

	render_body() {
		if (!this.$root) return;
		const $body = this.$root.find(".et-readiness-body").empty();

		if (this.frm.is_new()) {
			$body.html(`<div class="text-muted small">${__("Save first to evaluate e-invoicing readiness.")}</div>`);
			return;
		}

		const findings = this.findings || [];
		if (!findings.length) {
			$body.html(`<div class="et-wiz-ready">${frappe.utils.icon("tick-circle", "lg")} <span>${__("This party is ready for electronic invoicing.")}</span></div>`);
			return;
		}

		const $ul = $('<div class="et-wiz-checklist"></div>').appendTo($body);
		findings.forEach((f) => {
			const color = f.severity === "error" ? "red" : f.severity === "warning" ? "orange" : "blue";
			const $row = $(`
				<div class="et-wiz-check">
					<span class="et-wiz-dot ${color}"></span>
					<span class="et-wiz-check-label">${frappe.utils.escape_html(f.label)}</span>
					<a class="et-wiz-fix">${__("Fix")} →</a>
				</div>
			`);
			$row.find(".et-wiz-fix").on("click", () => this.fix(f));
			$ul.append($row);
		});
	}

	fix(finding) {
		if (finding.fix_doctype && finding.fix_name) {
			frappe.set_route("Form", finding.fix_doctype, finding.fix_name);
			return;
		}
		if (finding.fix_field) {
			// Native Frappe: switch to the field's tab and highlight it.
			this.frm.scroll_to_field(finding.fix_field);
		}
	}
};
