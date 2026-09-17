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

	// Sales and Purchase Invoice attach the lifecycle the same way: ask the server which
	// eInvoice the transaction belongs to, then render. Kept here so the two sides cannot
	// drift apart over which fields they forward.
	// `on_sent` is an optional per-doctype callback run after a status is successfully
	// reported, so a form can react to its own statuses (Supplier Invoice offers to close
	// itself after a refusal) without this shared module accumulating doctype special cases.
	attach_for_transaction(frm, { on_sent } = {}) {
		if (frm.is_new()) return;

		frappe.call({
			method: "etransactions.etransactions.doctype.einvoice.einvoice.get_transaction_einvoice",
			args: { doctype: frm.doctype, name: frm.doc.name },
			callback: (r) => {
				if (!r.message) return;
				this.attach(frm, {
					einvoice: r.message.name,
					side: r.message.side,
					pa_status: r.message.pa_status,
					pa_flow_id: r.message.pa_flow_id,
					pa_content_state: r.message.pa_content_state,
					pa_content_attempts: r.message.pa_content_attempts,
					pa_content_last_attempt: r.message.pa_content_last_attempt,
					group: __("eInvoicing"),
					on_sent,
				});
			},
			// The lifecycle panel is an add-on: a lookup failure must never throw a
			// traceback dialog over the invoice the user is working on.
			error: () => {},
		});
	},

	attach(frm, {
		einvoice,
		side,
		pa_status,
		pa_flow_id,
		pa_content_state,
		pa_content_attempts,
		pa_content_last_attempt,
		group,
		on_sent,
	}) {
		frm._et_lc = {
			einvoice,
			side,
			pa_status,
			pa_flow_id,
			pa_content_state,
			pa_content_attempts,
			pa_content_last_attempt,
			on_sent,
			lc: null,
		};
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
						// The hook may itself reload the form (Supplier Invoice closes itself
						// after a refusal), so give it the chance to run before after_send
						// rebuilds the buttons — otherwise the two race over the same form.
						const hook = frm._et_lc.on_sent;
						if (hook && hook(def, frm) === false) return;
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
				// The server sends {value, label, description}: the wire code is what travels,
				// the label is what the user reads. A Select (rather than an Autocomplete)
				// because the code list is closed — the server rejects anything outside it,
				// and there is no reason to let the user type a code that will be refused.
				const options = codes || [];
				const described = Object.fromEntries(
					options.filter((o) => o.description).map((o) => [o.value, o.description])
				);

				frappe.prompt(
					[
						{
							fieldname: "reason_code",
							fieldtype: "Select",
							label: __("Reason"),
							// Leading blank so nothing is preselected under reqd: 1 — the reason
							// travels to the platform and must be a deliberate choice.
							options: [{ value: "", label: "" }].concat(
								options.map((o) => ({ value: o.value, label: o.label }))
							),
							reqd: 1,
							change() {
								this.set_description(described[this.get_value()] || "");
							},
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
			})
			.catch(() => {
				// Unlike the panel's silent failures, this one follows a click: saying nothing
				// would look like the button is broken.
				frappe.msgprint({
					title: __("Reason codes unavailable"),
					message: __("The reason codes for '{0}' could not be loaded. Please try again.", [
						def.label,
					]),
					indicator: "red",
				});
			});
	},

	after_send(frm) {
		// A send changes which statuses are reportable next, so the buttons have to be
		// rebuilt, not just the timeline. Both paths clear the custom buttons and re-run
		// the form's refresh, which calls attach() again with fresh server data — on a
		// transaction that goes through attach_for_transaction(), which re-reads the
		// eInvoice, so nothing has to be refetched here.
		if (frm.doctype === "eInvoice") {
			frm.reload_doc();
		} else {
			frm.refresh();
		}
	},

	// The buyer's view of a received e-invoice: one headline saying where it stands, the
	// four steps of its lifecycle, the next actions as buttons, and the history. The
	// server reads the state (get_lifecycle_overview); this only draws it.
	attach_overview(frm, { einvoice, status_field, history_field, on_sent } = {}) {
		const status = frm.get_field(status_field);
		const history = frm.get_field(history_field);
		if (!status || !history) return;

		// A slow answer for a previous refresh must not overwrite a newer one.
		const token = (frm._et_overview_token = (frm._et_overview_token || 0) + 1);
		frm._et_lc = { einvoice, on_sent };

		frappe
			.xcall(
				"etransactions.etransactions.doctype.einvoice.einvoice.get_lifecycle_overview",
				{
					einvoice,
				}
			)
			.then((overview) => {
				if (token !== frm._et_overview_token) return;
				if (!overview) {
					status.$wrapper.empty();
					history.$wrapper.empty();
					return;
				}
				frm._et_lc.overview = overview;
				frm.dashboard.add_indicator(__("Platform: {0}", [overview.pill]), overview.tone);
				this.render_overview(frm, status.$wrapper, overview);
				this.render_history(frm, history.$wrapper, overview);
			})
			// An add-on panel: a failed lookup must not throw a dialog over the invoice.
			.catch(() => {});
	},

	// Which reportable statuses get a button of their own, per situation; the others go
	// under "More". Buttons for statuses the server does not offer are never drawn.
	MAIN_ACTIONS: {
		approved: ["payment_sent"],
		partially_approved: ["refused", "approved"],
		dispute: ["refused", "approved"],
		suspended: ["refused", "approved"],
		default: ["dispute", "refused", "approved"],
	},

	render_overview(frm, $wrapper, overview) {
		const esc = frappe.utils.escape_html;
		const by_status = Object.fromEntries((overview.actions || []).map((a) => [a.status, a]));
		const main_keys = (this.MAIN_ACTIONS[overview.key] || this.MAIN_ACTIONS.default).filter(
			(k) => by_status[k]
		);
		const more = (overview.actions || []).filter((a) => !main_keys.includes(a.status));
		const can_write = frm.perm[0] && frm.perm[0].write;

		const button = (a) => {
			const cls =
				a.status === "approved" || a.status === "payment_sent"
					? "btn-primary"
					: a.status === "refused"
					? "btn-default et-ov-danger"
					: "btn-default";
			return `<button class="btn btn-sm ${cls}" data-et-status="${esc(a.status)}">${esc(
				a.label
			)}</button>`;
		};

		let actions = "";
		if (can_write) {
			actions = main_keys.map((k) => button(by_status[k])).join("");
			if (more.length) {
				actions += `<div class="dropdown">
						<button class="btn btn-sm btn-default dropdown-toggle" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">${__(
							"More"
						)}</button>
						<div class="dropdown-menu dropdown-menu-right">
							${more
								.map(
									(a) =>
										`<a class="dropdown-item" href="#" data-et-status="${esc(
											a.status
										)}">${esc(a.label)}</a>`
								)
								.join("")}
						</div>
					</div>`;
			}
			if (overview.can_retry_download) {
				actions = `<button class="btn btn-sm btn-primary" data-et-retry-download="1">${__(
					"Retry download"
				)}</button>`;
			}
		}

		const blocked =
			!actions && overview.blocked_reason
				? `<div class="et-ov-blocked">${esc(overview.blocked_reason)}</div>`
				: "";

		const source = [
			overview.platform
				? `<span class="et-ov-platform">${esc(
						__("Received via {0}", [overview.platform])
				  )}</span>`
				: "",
			overview.flow_id
				? `<span>${__("Flow")} <code>${esc(overview.flow_id)}</code></span>`
				: "",
			`<a class="et-ov-open">${__("Open eInvoice")} →</a>`,
		]
			.filter(Boolean)
			.join("");

		const glyphs = { done: "✓", warning: "!", error: "×", skipped: "–" };
		const steps = overview.steps
			.map((s, i) => {
				const sub = [s.at ? frappe.datetime.str_to_user(s.at) : "", s.note || ""]
					.filter(Boolean)
					.join(" · ");
				return `<li class="et-ov-step is-${esc(s.state)}">
						<div class="et-ov-step-track">
							<span class="et-ov-step-dot">${glyphs[s.state] || i + 1}</span>
							<span class="et-ov-step-line"></span>
						</div>
						<div class="et-ov-step-label">${esc(s.label)}</div>
						<div class="et-ov-step-sub">${esc(sub || "—")}</div>
					</li>`;
			})
			.join("");

		$wrapper.html(`<div class="et-ov" data-et-overview="${esc(overview.key)}">
				<div class="et-ov-head">
					<div class="et-ov-text">
						<div class="et-ov-source">${source}</div>
						<div class="et-ov-headline">
							<span class="et-ov-dot tone-${esc(overview.tone)}"></span>
							<h3>${esc(overview.headline)}</h3>
						</div>
						<p class="et-ov-summary">${esc(overview.summary)}</p>
					</div>
					<div class="et-ov-actions">${actions}${blocked}</div>
				</div>
				<ol class="et-ov-steps">${steps}</ol>
			</div>`);

		$wrapper
			.find(".et-ov-open")
			.on("click", () => frappe.set_route("Form", "eInvoice", overview.einvoice));
		$wrapper.find("[data-et-status]").on("click", (e) => {
			e.preventDefault();
			const def = by_status[$(e.currentTarget).attr("data-et-status")];
			if (def) this.send_status(frm, def);
		});
		$wrapper.find("[data-et-retry-download]").on("click", () => {
			frappe
				.call({
					method: "etransactions.etransactions.doctype.einvoice.einvoice.retry_einvoice_content_fetch",
					args: { einvoice: overview.einvoice },
					freeze: true,
				})
				.then((r) => {
					if (r.exc) return;
					frappe.show_alert({
						message: __("Download queued. Reload the invoice in a moment."),
						indicator: "blue",
					});
				});
		});
	},

	HISTORY_LIMIT: 4,

	render_history(frm, $wrapper, overview) {
		const esc = frappe.utils.escape_html;
		const rows = overview.history || [];
		const expanded = !!frm._et_history_expanded;
		const shown = expanded ? rows : rows.slice(0, this.HISTORY_LIMIT);
		const by_status = Object.fromEntries((overview.actions || []).map((a) => [a.status, a]));

		const items = shown
			.map((r, i) => {
				const when = r.at ? frappe.datetime.str_to_user(r.at) : "";
				const code = r.code ? `<code class="et-ov-code">${esc(r.code)}</code>` : "";
				const reason = r.reason
					? `<div class="et-ov-reason"><strong>${esc(
							__("Reason: {0}", [r.reason])
					  )}</strong>${r.comment ? `<div>${esc(r.comment)}</div>` : ""}</div>`
					: r.comment
					? `<div class="et-ov-reason">${esc(r.comment)}</div>`
					: "";
				const retry =
					r.retry_status && by_status[r.retry_status]
						? `<button class="btn btn-xs btn-default et-ov-danger" data-et-status="${esc(
								r.retry_status
						  )}">${__("Retry")}</button>`
						: "";
				const delivery = r.delivery
					? `<div class="et-ov-delivery is-${esc(r.delivery)}">
							<span>${r.delivery === "error" ? "!" : r.delivery === "done" ? "✓" : "…"}</span>
							<span>${esc(r.delivery_label)}</span>${retry}
						</div>`
					: "";
				const error = r.error ? `<div class="et-ov-error">${esc(r.error)}</div>` : "";
				return `<li class="et-ov-event ${i === 0 ? "is-latest" : ""}">
						<span class="et-ov-event-dot tone-${esc(r.tone)}"></span>
						<div class="et-ov-event-body">
							<div class="et-ov-event-title">
								<span>${esc(r.title)}</span>${code}
								<span class="et-ov-event-when">${esc(when)}</span>
							</div>
							<div class="et-ov-event-meta">
								<span class="et-ov-actor tone-${esc(r.actor_tone)}">${esc(r.actor)}</span>
								${r.detail ? `<span>${esc(r.detail)}</span>` : ""}
							</div>
							${reason}${delivery}${error}
						</div>
					</li>`;
			})
			.join("");

		const toggle =
			rows.length > this.HISTORY_LIMIT
				? `<a class="et-ov-toggle">${
						expanded ? __("Show less") : __("Show all ({0})", [rows.length])
				  }</a>`
				: "";

		$wrapper.html(`<div class="et-ov-history">
				<div class="et-ov-history-head">${__("Platform history")}</div>
				<ol>${items}</ol>
				${toggle}
			</div>`);

		$wrapper.find(".et-ov-toggle").on("click", () => {
			frm._et_history_expanded = !expanded;
			this.render_history(frm, $wrapper, overview);
		});
		$wrapper.find("[data-et-status]").on("click", (e) => {
			const def = by_status[$(e.currentTarget).attr("data-et-status")];
			if (def) this.send_status(frm, def);
		});
	},

	render_timeline(frm) {
		const { einvoice, pa_status, pa_flow_id } = frm._et_lc;

		frappe.db
			.get_list("eInvoice Event", {
				filters: { einvoice },
				fields: [
					"direction",
					"status_label",
					"state",
					"status_datetime",
					"reason_code",
					"comment",
				],
				order_by: "status_datetime desc",
				limit: 20,
			})
			.then((events) => {
				const html =
					`<div class="et-lc" data-et-lifecycle="1" data-et-einvoice="${frappe.utils.escape_html(
						einvoice
					)}" data-et-pa-status="${frappe.utils.escape_html(pa_status || "")}">
						${this.ribbon_html(pa_status, pa_flow_id)}
						${this.content_state_html(frm._et_lc)}
						${this.state_html(frm._et_lc.lc)}
						${this.events_html(events || [], (frm._et_lc.lc || {}).reason_labels || {})}
						<div class="et-lc-link"><a class="et-lc-open">${__("Open eInvoice")} →</a></div>
					</div>`;
				if (frm._et_lc_section) {
					frm._et_lc_section.remove();
				}
				frm._et_lc_section = frm.dashboard.add_section(html, __("e-Invoicing Lifecycle"));
				frm._et_lc_section
					.find(".et-lc-open")
					.on("click", () => frappe.set_route("Form", "eInvoice", einvoice));
			});
	},

	// An e-invoice that never went through an accredited platform (received by email or
	// uploaded as a file) has no transmission to show. Its events and party states still
	// matter, so only the ribbon is suppressed.
	ribbon_html(pa_status, pa_flow_id) {
		if (!pa_flow_id) return "";

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

		return `<div class="et-lc-ribbon">${steps}</div>${err}`;
	},

	// The original file is downloaded after the flow is recorded, so an invoice can be
	// known but not yet readable. Saying so beats showing an empty lifecycle.
	content_state_html({ pa_content_state, pa_content_attempts, pa_content_last_attempt }) {
		if (pa_content_state === "pending") {
			// After a couple of tries this has stopped being "not yet" and become "not
			// working" — say which, so a stuck invoice cannot read as a transient one.
			const detail =
				pa_content_attempts > 1
					? " " +
					  __("Tried {0} times, last on {1}.", [
							pa_content_attempts,
							frappe.datetime.str_to_user(pa_content_last_attempt),
					  ])
					: "";
			return `<div class="et-lc-content-state text-muted" data-et-content-state="pending">${__(
				"The original file has not been downloaded from the platform yet."
			)}${frappe.utils.escape_html(detail)}</div>`;
		}
		if (pa_content_state === "error") {
			return `<div class="et-lc-content-state" style="color:var(--red-500)" data-et-content-state="error">${__(
				"The original file could not be downloaded or parsed — see the eInvoice for details."
			)}</div>`;
		}
		return "";
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
					${frappe.utils.escape_html(__("{0}: {1}", [title, axis.label]))}${when}
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

	// `reason_labels` maps the stored MDT-113 code to its wording: a refusal's reason is
	// the whole point of the row, and "NON_CONFORME" is not an answer to "why".
	events_html(events, reason_labels = {}) {
		if (!events.length) return "";
		const rows = events
			.map((e) => {
				const arrow =
					e.direction === "out"
						? `<span style="color:var(--blue-500)">&#8593; ${__("Sent")}</span>`
						: `<span style="color:var(--orange-500)">&#8595; ${__("Received")}</span>`;
				const when = e.status_datetime ? frappe.datetime.str_to_user(e.status_datetime) : "";
				const state_labels = {
					created: __("Created"),
					sent: __("Sent"),
					done: __("Done"),
					error: __("Error"),
				};
				const state_label = frappe.utils.escape_html(
					e.state ? state_labels[e.state] || __(e.state) : ""
				);
				const state =
					e.state === "error"
						? `<span style="color:var(--red-500)">${state_label}</span>`
						: state_label;
				const reason_label = e.reason_code
					? reason_labels[e.reason_code] || e.reason_code
					: "";
				const reason = [reason_label, e.comment]
					.filter(Boolean)
					.map((part) => frappe.utils.escape_html(part))
					.join(" — ");
				return `<tr>
						<td>${arrow}</td>
						<td><strong>${frappe.utils.escape_html(e.status_label ? __(e.status_label) : "")}</strong></td>
						<td>${state}</td>
						<td>${when}</td>
						<td>${reason}</td>
					</tr>`;
			})
			.join("");

		return `<table class="table table-bordered et-lc-events" style="margin-top:12px">
				<thead><tr>
					<th>${__("Direction")}</th>
					<th>${__("Status")}</th>
					<th>${__("State")}</th>
					<th>${__("Date/Time")}</th>
					<th>${__("Reason")}</th>
				</tr></thead>
				<tbody>${rows}</tbody>
			</table>`;
	},
};
