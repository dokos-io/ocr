// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt
//
// Live e-invoicing readiness panel for Sales / Purchase Invoice. Runs a dry-run
// readiness check on the in-memory (possibly unsaved) document so problems show
// up *while* the user fills the invoice, in the shared status vocabulary.

frappe.provide("etransactions");

etransactions.invoiceReadiness = {
	refresh(frm) {
		if (!frm.fields_dict.etransactions_status_html) return;
		if (frm.doctype === "Sales Invoice" && !frm.doc.etransaction_profile) return;
		if (frm.doctype === "Purchase Invoice" && !frm.doc.supplier) return;
		frm._et_live = frm._et_live || frappe.utils.debounce(() => this._fetch(frm), 350);
		frm._et_live();
	},

	_fetch(frm) {
		frappe.call({
			method: "etransactions.plateforme_agreee.readiness.check_invoice_readiness",
			args: { doc: frm.doc },
			callback: (r) => this._render(frm, r.message || []),
		});
	},

	_render(frm, findings) {
		const field = frm.fields_dict.etransactions_status_html;
		if (!field) return;

		const errors = findings.filter((f) => f.severity === "error");
		const warnings = findings.filter((f) => f.severity === "warning");
		const color = errors.length ? "red" : warnings.length ? "orange" : "green";
		const label = errors.length
			? __("{0} blocking issue(s)", [errors.length])
			: warnings.length
			? __("{0} warning(s)", [warnings.length])
			: __("Ready for e-invoicing");

		const $wrap = $('<div class="et-inv-readiness"></div>');
		$wrap.append(`<span class="indicator-pill ${color}">${label}</span>`);

		if (findings.length) {
			const $list = $('<div class="et-inv-findings"></div>');
			findings.forEach((f) => {
				const dot = f.severity === "error" ? "red" : f.severity === "warning" ? "orange" : "blue";
				const $row = $(`
					<div class="et-inv-finding">
						<span class="et-wiz-dot ${dot}"></span>
						<span class="et-inv-finding-label">${frappe.utils.escape_html(f.label)}</span>
						<a class="et-inv-fix">${__("Fix")} →</a>
					</div>
				`);
				$row.find(".et-inv-fix").on("click", () => this._fix(frm, f));
				$list.append($row);
			});
			$wrap.append($list);
		}

		field.$wrapper.empty().append($wrap);
	},

	_fix(frm, finding) {
		if (finding.fix_doctype && finding.fix_name) {
			frappe.set_route("Form", finding.fix_doctype, finding.fix_name);
			return;
		}
		if (finding.fix_field) {
			frm.scroll_to_field(finding.fix_field);
		}
	},

	// Consolidated pre-submit gate: one confirm listing all blocking issues.
	gate(frm) {
		return new Promise((resolve, reject) => {
			frappe.call({
				method: "etransactions.plateforme_agreee.readiness.check_invoice_readiness",
				args: { doc: frm.doc },
				callback: (r) => {
					const errors = (r.message || []).filter((f) => f.severity === "error");
					if (!errors.length) {
						resolve();
						return;
					}
					const list = errors.map((f) => `<li>${frappe.utils.escape_html(f.label)}</li>`).join("");
					frappe.confirm(
						`${__("This invoice has e-invoicing issues that may cause it to be rejected:")}
						<ul style="margin-top:8px">${list}</ul>
						${__("Submit anyway?")}`,
						() => resolve(),
						() => reject()
					);
				},
				error: () => resolve(),
			});
		});
	},
};
