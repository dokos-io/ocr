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
		// No profile is NOT a reason to stay silent on a Sales Invoice: the
		// server reports "missing profile" as a finding for B2B/B2G customers
		// (the profile is the pipeline's master switch).
		if (frm.doctype === "Sales Invoice" && !frm.doc.customer) return;
		if (frm.doctype === "Purchase Invoice" && !frm.doc.supplier) return;
		frm._et_live = frm._et_live || frappe.utils.debounce(() => this._fetch(frm), 350);
		frm._et_live();
	},

	_fetch(frm) {
		// Live (pre-send) readiness on the in-memory doc + the post-send platform
		// state (status + rejection/validation reasons) in one panel.
		const live = frappe.call({
			method: "etransactions.plateforme_agreee.readiness.check_invoice_readiness",
			args: { doc: frm.doc },
		});
		const panel =
			frm.doc.docstatus === 1 && !frm.is_new()
				? frappe.call({
						method: "etransactions.plateforme_agreee.readiness.get_einvoice_panel",
						args: { doctype: frm.doctype, name: frm.doc.name },
				  })
				: Promise.resolve({ message: {} });

		Promise.all([live, panel]).then(([l, p]) =>
			this._render(frm, l.message || [], p.message || {})
		);
	},

	// Color for a platform pa_status badge.
	_status_meta(status) {
		const map = {
			rejected: ["red", __("Rejected by the platform")],
			error: ["red", __("Transmission error")],
			done: ["green", __("Accepted")],
			pending: ["blue", __("In processing")],
			sent: ["blue", __("Sent")],
			created: ["gray", __("Created")],
		};
		return map[status] || ["gray", status ? __(status) : ""];
	},

	_render(frm, findings, panel) {
		const field = frm.fields_dict.etransactions_status_html;
		if (!field) return;

		// data-et-* are stable hooks for the Cypress suite: the visible labels are
		// translated, so specs must not select on them.
		const $wrap = $('<div class="et-inv-readiness" data-et-readiness="1"></div>').attr(
			"data-et-pa-status",
			(panel && panel.pa_status) || ""
		);

		// --- Post-send: platform status badge + rejection/validation reasons ---
		if (panel && panel.pa_status) {
			const [color, label] = this._status_meta(panel.pa_status);
			$wrap.append(`<span class="indicator-pill ${color}">${frappe.utils.escape_html(label)}</span>`);
			const problems = panel.problems || [];
			if (problems.length) {
				$wrap.append(this._findings_list(frm, problems));
			}
		}

		// --- Pre-send readiness (hidden once the platform has accepted it) ---
		const showLive = !(panel && ["done", "pending", "sent"].includes(panel.pa_status));
		if (showLive) {
			const errors = findings.filter((f) => f.severity === "error");
			const warnings = findings.filter((f) => f.severity === "warning");
			const color = errors.length ? "red" : warnings.length ? "orange" : "green";
			const label = errors.length
				? __("{0} blocking issue(s)", [errors.length])
				: warnings.length
				? __("{0} warning(s)", [warnings.length])
				: __("Ready for e-invoicing");
			if (!(panel && panel.pa_status)) {
				$wrap.append(`<span class="indicator-pill ${color}">${label}</span>`);
			}
			if (findings.length) {
				$wrap.append(this._findings_list(frm, findings));
			}
		}

		field.$wrapper.empty().append($wrap);
	},

	_findings_list(frm, findings) {
		const $list = $('<div class="et-inv-findings"></div>');
		findings.forEach((f) => {
			const dot = f.severity === "error" ? "red" : f.severity === "warning" ? "orange" : "blue";
			const fixable = (f.fix_doctype && f.fix_name) || f.fix_field;
			const $row = $(`
				<div class="et-inv-finding">
					<span class="et-wiz-dot ${dot}"></span>
					<span class="et-inv-finding-label">${frappe.utils.escape_html(f.label)}</span>
					${fixable ? `<a class="et-inv-fix">${__("Fix")} →</a>` : ""}
				</div>
			`);
			if (fixable) {
				$row.find(".et-inv-fix").on("click", () => this._fix(frm, f));
			}
			$list.append($row);
		});
		return $list;
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
	// When the server-side hard gate is on (eTransactions Settings), skip the
	// confirm — before_submit refuses the submission with the same list.
	gate(frm) {
		return new Promise((resolve, reject) => {
			frappe.call({
				method: "etransactions.plateforme_agreee.readiness.check_invoice_readiness",
				args: { doc: frm.doc },
				callback: async (r) => {
					const errors = (r.message || []).filter((f) => f.severity === "error");
					if (!errors.length) {
						resolve();
						return;
					}
					const hard_gate = await frappe.db
						.get_single_value("eTransactions Settings", "block_submission_on_blocking_findings")
						.catch(() => 0);
					if (hard_gate) {
						resolve(); // the server hook enforces and lists the issues
						return;
					}
					const list = errors
						.map((f) => {
							const detail = f.detail
								? `<div class="text-muted small" style="margin:2px 0 6px">${f.detail}</div>`
								: "";
							return `<li>${frappe.utils.escape_html(f.label)}${detail}</li>`;
						})
						.join("");
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
