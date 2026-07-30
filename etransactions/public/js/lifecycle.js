// Copyright (c) 2026, ALYF GmbH, Dokos SAS and contributors
// For license information, please see license.txt
//
// Shared e-invoicing lifecycle UI: a transmission ribbon + event timeline and
// the "Report Status" actions. Used by the eInvoice form and embedded directly
// in Sales / Purchase Invoice so the lifecycle can be followed and driven from
// the transaction the user already works in.

frappe.provide("etransactions");

etransactions.lifecycle = {
	// The reportable statuses and their metadata (label, reason code, confirmation)
	// come from the server: it owns the status registry and is the only side that can
	// tell which statuses the platform carries and which the invoice's current state
	// still allows. Keeping a copy here would drift from the rules actually enforced.

	// Linear PA transmission ribbon.
	PA_RIBBON: [
		{ key: "created", label: __("Created") },
		{ key: "sent", label: __("Sent") },
		{ key: "pending", label: __("Pending") },
		{ key: "done", label: __("Done") },
	],

	attach(frm, { einvoice, side, pa_status, group }) {
		frm._et_lc = { einvoice, side, pa_status, lc: null };
		frappe
			.xcall(
				"etransactions.etransactions.doctype.einvoice.einvoice.get_supported_lifecycle_statuses",
				{ einvoice }
			)
			.then((lc) => {
				frm._et_lc.lc = lc;
				this.add_buttons(frm, (lc || {}).statuses, group);
				this.render_timeline(frm);
			})
			.catch(() => {
				// No fallback list on purpose: guessing would offer statuses the server
				// is going to reject. The timeline still renders.
				this.render_timeline(frm);
			});
	},

	add_buttons(frm, statuses, group) {
		(statuses || []).forEach((def) => {
			frm.add_custom_button(def.label, () => this.send_status(frm, def), group || __("Report Status"));
		});
	},

	send_status(frm, def) {
		const einvoice = frm._et_lc.einvoice;
		const run = (args) => {
			frappe
				.call({
					method: "etransactions.etransactions.doctype.einvoice.einvoice.report_lifecycle_status",
					args: { einvoice, status: def.status, ...args },
					freeze: true,
					freeze_message: __("Sending status to the accredited platform…"),
				})
				.then((r) => {
					if (!r.exc) {
						frappe.show_alert({ message: __("Status '{0}' sent", [def.label]), indicator: "green" });
						this.after_send(frm);
					}
				});
		};

		// The confirmation is about the status being irreversible, so it gates the send
		// whether or not a reason code is collected along the way.
		const confirm_then = (proceed) => {
			if (!def.confirm) {
				proceed();
				return;
			}
			const msg =
				def.confirm_message || __("Reporting '{0}' cannot be undone. Continue?", [def.label]);
			frappe.confirm(msg, proceed);
		};

		if (!def.reason) {
			confirm_then(() => run({}));
			return;
		}

		frappe
			.xcall("etransactions.etransactions.doctype.einvoice.einvoice.get_lifecycle_reason_codes", {
				status: def.status,
			})
			.then((codes) => {
				frappe.prompt(
					[
						{
							fieldname: "reason_code",
							fieldtype: "Select",
							label: __("Reason code"),
							options: (codes || []).join("\n"),
							reqd: 1,
						},
						{ fieldname: "comment", fieldtype: "Small Text", label: __("Comment (optional)") },
					],
					(values) => {
						confirm_then(() =>
							run({ reason_code: values.reason_code, comment: values.comment })
						);
					},
					__("Report '{0}'", [def.label]),
					__("Send")
				);
			});
	},

	after_send(frm) {
		// A send changes which statuses are reportable next, so the buttons have to be
		// rebuilt, not just the timeline. Both paths clear the custom buttons and re-run
		// the form's refresh, which calls attach() again with fresh server data.
		if (frm.doctype === "eInvoice") {
			frm.reload_doc();
		} else {
			frappe.db.get_value("eInvoice", frm._et_lc.einvoice, "pa_status").then((r) => {
				frm._et_lc.pa_status = (r.message || {}).pa_status;
				frm.refresh();
			});
		}
	},

	render_timeline(frm) {
		const { einvoice, pa_status } = frm._et_lc;

		frappe.db
			.get_list("eInvoice Event", {
				filters: { einvoice },
				fields: ["direction", "status_label", "state", "status_datetime", "comment"],
				order_by: "status_datetime desc",
				limit: 20,
			})
			.then((events) => {
				const html =
					this.ribbon_html(pa_status) +
					this.state_html(frm._et_lc.lc) +
					this.events_html(events || []);
				if (frm._et_lc_section) {
					frm._et_lc_section.remove();
				}
				frm._et_lc_section = frm.dashboard.add_section(html, __("e-Invoicing Lifecycle"));
				frm._et_lc_section
					.find(".et-lc-open")
					.on("click", () => frappe.set_route("Form", "eInvoice", einvoice));
			});
	},

	ribbon_html(pa_status) {
		const error = pa_status === "error" || pa_status === "rejected";
		const reached = this.PA_RIBBON.findIndex((s) => s.key === pa_status);
		const steps = this.PA_RIBBON.map((s, i) => {
			let cls = "";
			if (error) cls = "is-error";
			else if (i < reached) cls = "is-done";
			else if (i === reached) cls = "is-active";
			return `<div class="et-lc-step ${cls}">
					<span class="et-lc-dot"></span>
					<span class="et-lc-step-label">${frappe.utils.escape_html(s.label)}</span>
				</div>`;
		}).join('<span class="et-lc-line"></span>');

		const err = error
			? `<div class="et-lc-error">${frappe.utils.icon("solid-error", "sm")} ${
					pa_status === "rejected"
						? __("Rejected by the accredited platform — see the issues in the e-invoicing panel.")
						: __("Transmission error — see the issues in the e-invoicing panel.")
			  }</div>`
			: "";

		return `<div class="et-lc">
				<div class="et-lc-ribbon">${steps}</div>
				${err}
				<div class="et-lc-link"><a class="et-lc-open">${__("Open eInvoice")} →</a></div>
			</div>`;
	},

	// Where each side of the lifecycle currently stands, plus — when no status can be
	// reported any more — why. Without it, a refused invoice just shows an empty action
	// group and the user cannot tell whether that is a bug or a rule.
	state_html(lc) {
		if (!lc || !lc.state) return "";

		const colors = { success: "green", danger: "red", warning: "orange", info: "blue" };
		const chip = (title, axis) => {
			if (!axis || !axis.status) return "";
			const when = axis.reported_at ? ` · ${frappe.datetime.str_to_user(axis.reported_at)}` : "";
			return `<span class="indicator-pill ${colors[axis.decoration] || "gray"}" style="margin-right:8px">
					${frappe.utils.escape_html(title)}: ${frappe.utils.escape_html(axis.label)}${when}
				</span>`;
		};

		const chips = chip(__("Buyer"), lc.state.purchase) + chip(__("Seller"), lc.state.sale);
		const blocked = lc.blocked_reason
			? `<div class="text-muted" style="margin-top:6px">${frappe.utils.escape_html(
					lc.blocked_reason
			  )}</div>`
			: "";

		if (!chips && !blocked) return "";
		return `<div style="margin-top:10px">${chips}${blocked}</div>`;
	},

	events_html(events) {
		if (!events.length) return "";
		const rows = events
			.map((e) => {
				const arrow =
					e.direction === "out"
						? `<span style="color:var(--blue-500)">&#8593; ${__("Sent")}</span>`
						: `<span style="color:var(--orange-500)">&#8595; ${__("Received")}</span>`;
				const when = e.status_datetime ? frappe.datetime.str_to_user(e.status_datetime) : "";
				const state =
					e.state === "error"
						? `<span style="color:var(--red-500)">${e.state}</span>`
						: e.state || "";
				return `<tr>
						<td>${arrow}</td>
						<td><strong>${frappe.utils.escape_html(e.status_label || "")}</strong></td>
						<td>${state}</td>
						<td>${when}</td>
						<td>${frappe.utils.escape_html(e.comment || "")}</td>
					</tr>`;
			})
			.join("");

		return `<table class="table table-bordered" style="margin-top:12px">
				<thead><tr>
					<th>${__("Direction")}</th>
					<th>${__("Status")}</th>
					<th>${__("State")}</th>
					<th>${__("Date/Time")}</th>
					<th>${__("Comment")}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>`;
	},
};
