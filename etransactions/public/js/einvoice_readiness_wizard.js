// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt
//
// Guided, editable e-invoicing readiness wizard for master data (Customer /
// Supplier). Modelled on the Payment Entry wizard: a parallel UI mounted on an
// HTML field that reuses the native field definitions via make_control and
// writes back through frm.set_value, so all validation and cascades still fire.
// The underlying fields are hidden — this component is their editor.

frappe.provide("etransactions");

etransactions.EinvoiceReadinessWizard = class EinvoiceReadinessWizard {
	constructor(frm) {
		this.frm = frm;
		this.party_type = frm.doctype; // "Customer" | "Supplier"
		this.current = 0;
		this.controls = {};
		this.steps = this._steps();
		this._refresh_readiness = frappe.utils.debounce(() => this.load_readiness(), 400);
	}

	get field() {
		return this.frm.fields_dict.etransactions_wizard_html;
	}

	// ----- step definitions -------------------------------------------------

	_steps() {
		const identity = {
			key: "identity",
			label: __("Identity"),
			fields: ["siren_number", "tax_id"],
			render: (c) => this.render_fields(c, ["siren_number", "tax_id", "etransaction_profile"]),
		};
		const electronic = {
			key: "electronic",
			label: __("Electronic address"),
			fields: [
				"etransactions_electronic_address_scheme",
				"etransactions_electronic_address",
				"etransactions_buyer_reference",
				"etransactions_contract_reference",
			],
			render: (c) =>
				this.render_fields(c, [
					"etransactions_electronic_address_scheme",
					"etransactions_electronic_address",
					"etransactions_buyer_reference",
					"etransactions_contract_reference",
				]),
		};
		const review = {
			key: "review",
			label: __("Review"),
			fields: [],
			render: (c) => this.render_review(c),
		};

		if (this.party_type === "Supplier") {
			// Suppliers: identity + a minimal electronic address, then review.
			return [
				{ ...identity, render: (c) => this.render_fields(c, ["siren_number", "tax_id"]) },
				{
					...electronic,
					render: (c) =>
						this.render_fields(c, [
							"etransactions_electronic_address_scheme",
							"etransactions_electronic_address",
						]),
				},
				review,
			];
		}

		return [
			{ ...identity, render: (c) => this.render_fields(c, ["siren_number", "tax_id", "etransaction_profile"]) },
			{
				key: "routing",
				label: __("Establishments & routing"),
				fields: ["default_directory_line"],
				render: (c) => this.render_routing(c),
			},
			electronic,
			review,
		];
	}

	// ----- lifecycle --------------------------------------------------------

	refresh() {
		if (!this.field) return;
		this.render();
		this.load_readiness();
	}

	render() {
		const $w = $(this.field.wrapper).empty();
		this.$root = $(`
			<div class="et-wiz">
				<div class="et-wiz-head">
					<div class="et-wiz-readiness"></div>
				</div>
				<div class="et-wiz-nav"></div>
				<div class="et-wiz-body"></div>
				<div class="et-wiz-footer"></div>
			</div>
		`).appendTo($w);

		this.render_nav();
		this.render_body();
		this.render_footer();
		this.render_readiness();
	}

	render_nav() {
		const $nav = this.$root.find(".et-wiz-nav").empty();
		this.steps.forEach((step, i) => {
			const state = i === this.current ? "is-active" : i < this.current ? "is-done" : "";
			const $circle = $(`
				<button type="button" class="et-wiz-step ${state}">
					<span class="et-wiz-circle">${i < this.current ? frappe.utils.icon("tick", "xs") : i + 1}</span>
					<span class="et-wiz-step-label">${frappe.utils.escape_html(step.label)}</span>
				</button>
			`);
			$circle.on("click", () => this.go(i));
			$nav.append($circle);
			if (i < this.steps.length - 1) $nav.append('<span class="et-wiz-sep"></span>');
		});
	}

	render_body() {
		const $body = this.$root.find(".et-wiz-body").empty();
		this.controls = {};
		this.steps[this.current].render($body);
	}

	render_footer() {
		const $f = this.$root.find(".et-wiz-footer").empty();
		const last = this.current === this.steps.length - 1;

		const $back = $(`<button type="button" class="btn btn-default btn-sm">${__("Back")}</button>`);
		$back.prop("disabled", this.current === 0).on("click", () => this.go(this.current - 1));
		$f.append($back);

		const $spacer = $('<span style="flex:1"></span>');
		$f.append($spacer);

		if (this.frm.is_dirty()) {
			const $save = $(`<button type="button" class="btn btn-primary btn-sm">${__("Save")}</button>`);
			$save.on("click", () => this.frm.save());
			$f.append($save);
		}

		if (!last) {
			const $next = $(`<button type="button" class="btn btn-default btn-sm">${__("Next")}</button>`);
			$next.on("click", () => this.go(this.current + 1));
			$f.append($next);
		}
	}

	go(i) {
		this.current = Math.max(0, Math.min(this.steps.length - 1, i));
		this.render();
	}

	// ----- field rendering --------------------------------------------------

	render_fields($container, fieldnames) {
		const $grid = $('<div class="et-wiz-fields"></div>').appendTo($container);
		fieldnames.forEach((fieldname) => this.make_field(fieldname, $grid));
	}

	make_field(fieldname, $parent) {
		const base = this.frm.get_field(fieldname);
		if (!base) return;
		const df = Object.assign({}, base.df, { hidden: 0, read_only: base.df.read_only ? 1 : 0 });

		const $cell = $('<div class="et-wiz-field"></div>').appendTo($parent);
		const control = frappe.ui.form.make_control({
			df: df,
			parent: $cell.get(0),
			render_input: true,
			only_input: false,
			doc: this.frm.doc,
			// doctype/docname are required alongside frm: refresh_input() reads the
			// displayed value via frappe.model.get_value(doctype, docname, field).
			// Without them the lookup returns null and the control renders empty.
			doctype: this.frm.doctype,
			docname: this.frm.docname,
			frm: this.frm,
		});
		control.set_value(this.frm.doc[fieldname]);
		control.refresh();

		const commit = () => {
			const val = control.get_value();
			if (val !== this.frm.doc[fieldname]) {
				this.frm.set_value(fieldname, val).then(() => {
					this._refresh_readiness();
					this.refresh_footer();
				});
			}
		};
		control.df.onchange = commit;
		if (control.$input) control.$input.on("change blur", commit);

		this.controls[fieldname] = control;
		return control;
	}

	// Push every mounted control's value into the form model. Called on before_save
	// so pending edits are persisted regardless of the save path. frm.set_value's
	// model update is synchronous, so values land before serialization.
	flush() {
		Object.entries(this.controls).forEach(([fieldname, control]) => {
			const val = control.get_value();
			if (val !== this.frm.doc[fieldname]) {
				this.frm.set_value(fieldname, val);
			}
		});
	}

	refresh_footer() {
		if (this.$root) this.render_footer();
	}

	// ----- establishments & routing ----------------------------------------

	render_routing($container) {
		if (this.frm.is_new()) {
			$container.html(`<div class="et-wiz-empty">${__("Save the customer first to manage establishments and routing.")}</div>`);
			return;
		}

		const $head = $(`
			<div class="et-wiz-routing-head">
				<div class="text-muted small">${__("Each establishment (address) routes through its own SIRET. Pick a default for invoices with no establishment match.")}</div>
				<button type="button" class="btn btn-xs btn-default et-wiz-sync">${frappe.utils.icon("refresh", "xs")} ${__("Sync directory")}</button>
			</div>
		`).appendTo($container);

		$head.find(".et-wiz-sync").on("click", () => this.sync_directory());

		const $default = $('<div class="et-wiz-field et-wiz-default-line"></div>').appendTo($container);
		this.make_field("default_directory_line", $default);
		// Restrict the default line to this customer's lines.
		const ctrl = this.controls.default_directory_line;
		if (ctrl) {
			ctrl.get_query = () => ({ filters: { customer: this.frm.doc.name } });
		}

		const $list = $('<div class="et-wiz-estab"></div>').appendTo($container);
		$list.html(`<div class="text-muted small">${frappe.utils.icon("loading-indicator")} ${__("Loading establishments…")}</div>`);

		frappe.call({
			method: "etransactions.plateforme_agreee.directory.get_party_establishments",
			args: { party_type: this.party_type, party: this.frm.doc.name },
			callback: (r) => this.render_establishments($list, r.message || []),
		});
	}

	render_establishments($list, rows) {
		$list.empty();
		if (!rows.length) {
			$list.html(`<div class="et-wiz-empty">${__("No addresses linked to this customer yet.")}</div>`);
			return;
		}

		rows.forEach((row) => {
			const line = row.line;
			let routing;
			if (!row.siret_number) {
				routing = `<span class="indicator-pill orange">${__("No SIRET")}</span>`;
			} else if (line) {
				const color = line.line_status === "active" ? "green" : line.line_status === "upcoming" ? "blue" : "gray";
				routing = `<span class="indicator-pill ${color}">${frappe.utils.escape_html(line.routing_code_name || line.line_status)}</span>`;
				if (line.commitment_required) {
					routing += ` <span class="et-wiz-commit" title="${__("Every invoice to this route needs a purchase-order / commitment number.")}">${__("commitment required")}</span>`;
				}
			} else {
				routing = `<span class="indicator-pill gray">${__("No routing line — sync directory")}</span>`;
			}

			const primary = row.is_primary ? `<span class="et-wiz-primary">${__("primary")}</span>` : "";
			const $card = $(`
				<div class="et-wiz-card">
					<div class="et-wiz-card-main">
						<div class="et-wiz-card-title">${frappe.utils.escape_html(row.title || row.address)} ${primary}</div>
						<div class="et-wiz-card-sub">${__("SIRET")}: ${frappe.utils.escape_html(row.siret_number || "—")}</div>
					</div>
					<div class="et-wiz-card-routing">${routing}</div>
					<button type="button" class="et-icon-btn et-wiz-open" title="${__("Open address")}">${frappe.utils.icon("edit", "xs")}</button>
				</div>
			`);
			$card.find(".et-wiz-open").on("click", () => frappe.set_route("Form", "Address", row.address));
			$list.append($card);
		});
	}

	sync_directory() {
		frappe.call({
			method: "etransactions.plateforme_agreee.directory.sync_customer_directory",
			args: { customer: this.frm.doc.name },
			freeze: true,
			freeze_message: __("Syncing directory lines…"),
			callback: () => {
				this.render();
				this.load_readiness();
			},
		});
	}

	// ----- readiness (the signature element) --------------------------------

	load_readiness() {
		frappe.call({
			method: "etransactions.plateforme_agreee.readiness.evaluate_party_readiness",
			args: { party_type: this.party_type, party: this.frm.doc.name },
			callback: (r) => {
				this.findings = r.message || [];
				this.render_readiness();
				if (this.steps[this.current].key === "review") this.render_body();
			},
		});
	}

	readiness_state() {
		const f = this.findings || [];
		if (f.some((x) => x.severity === "error")) return ["red", __("Not ready to invoice")];
		if (f.some((x) => x.severity === "warning")) return ["orange", __("Almost ready")];
		return ["green", __("Ready to invoice")];
	}

	render_readiness() {
		if (!this.$root) return;
		const [color, label] = this.readiness_state();
		this.$root.find(".et-wiz-readiness").html(`<span class="indicator-pill ${color}">${label}</span>`);
	}

	render_review($container) {
		const findings = this.findings || [];
		if (!findings.length) {
			$container.html(`<div class="et-wiz-ready">${frappe.utils.icon("tick-circle", "lg")} <span>${__("This customer is ready for electronic invoicing.")}</span></div>`);
			return;
		}

		const $ul = $('<div class="et-wiz-checklist"></div>').appendTo($container);
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
			const idx = this.steps.findIndex((s) => (s.fields || []).includes(finding.fix_field));
			if (idx >= 0) {
				this.go(idx);
				setTimeout(() => {
					const ctrl = this.controls[finding.fix_field];
					if (ctrl && ctrl.$input) ctrl.$input.focus();
				}, 150);
			}
		}
	}
};
