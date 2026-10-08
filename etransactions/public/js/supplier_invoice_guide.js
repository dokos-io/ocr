// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt
//
// The Review tab of a Supplier Invoice: where it stands, what to do next and the data
// read from the invoice next to the original document. The server decides everything
// (ProcessingGuide in processing_guide.py); this file only draws it and turns the
// action names it sends into calls to the form's existing methods.

frappe.provide("etransactions");

etransactions.supplierInvoiceGuide = {
	render(frm) {
		const $guide = frm.get_field("guide_html")?.$wrapper;
		if (!$guide) return;
		if (frm.is_new()) {
			$guide.empty();
			frm.get_field("review_summary_html")?.$wrapper.empty();
			frm.get_field("review_lines_html")?.$wrapper.empty();
			return;
		}

		// A slow answer for a previous refresh must not overwrite a newer one.
		const token = (frm._si_guide_token = (frm._si_guide_token || 0) + 1);
		frm.call("get_processing_guide")
			.then((r) => {
				if (token !== frm._si_guide_token || !r.message) return;
				const guide = r.message;
				frm._si_guide = guide;
				frm._et_lc = {
					einvoice: frm.doc.einvoice,
					overview: guide.platform,
					on_sent: frm._si_on_sent,
				};
				this.render_guide(frm, $guide, guide);
				this.render_summary(frm, guide);
				this.render_lines(frm, guide);
				this.set_indicator(frm, guide);
			})
			// An add-on panel: a failed lookup must not throw a dialog over the invoice.
			.catch(() => {});
	},

	set_indicator(frm, guide) {
		frm.page.set_indicator(guide.status.label, guide.status.tone);
	},

	// --- Guide panel ---------------------------------------------------------------------

	is_collapsed(frm) {
		return !!(frappe.model.user_settings[frm.doctype] || {}).guide_collapsed;
	},

	set_collapsed(frm, collapsed) {
		frappe.model.user_settings.save(frm.doctype, "guide_collapsed", collapsed ? 1 : 0);
		this.render_guide(frm, frm.get_field("guide_html").$wrapper, frm._si_guide);
	},

	render_guide(frm, $wrapper, guide) {
		const esc = frappe.utils.escape_html;
		const collapsed = this.is_collapsed(frm);
		const next = guide.next_step || {};
		const can_write = frm.perm[0] && frm.perm[0].write;

		const status_pill = `<span class="indicator-pill ${esc(guide.status.tone)}">${esc(
			guide.status.label
		)}</span>`;
		const platform_line = guide.platform
			? `${__("What the supplier sees")}: <strong>${esc(guide.platform_line)}</strong>`
			: esc(guide.platform_line);
		const open_checks = guide.open_checks
			? `<span class="indicator-pill orange no-indicator-dot">${esc(
					__("{0} check(s) open", [guide.open_checks])
			  )}</span>`
			: `<span class="indicator-pill green no-indicator-dot">${__(
					"All checks pass"
			  )}</span>`;
		const primary = can_write && next.primary ? this.button(next.primary, "btn-primary") : "";

		if (collapsed) {
			$wrapper.html(`<div class="si-guide is-collapsed">
					<div class="si-guide-mini">
						<div class="si-guide-mini-row">
							${status_pill}
							<ol class="si-guide-mini-steps" aria-label="${__("Progress")}">${this.mini_steps(guide.steps)}</ol>
							<span class="si-guide-platform">${platform_line}</span>
						</div>
						<div class="si-guide-mini-row">
							<span class="si-guide-mini-next"><span class="si-guide-eyebrow">${__("Next")}</span> ${esc(
				next.title || ""
			)}</span>
							${open_checks}
							<span class="si-guide-acts">${primary}
								<button class="btn btn-xs btn-link" data-si-toggle="expand" aria-expanded="false">${__(
									"Show guide"
								)} ▾</button>
							</span>
						</div>
					</div>
				</div>`);
			this.bind(frm, $wrapper);
			return;
		}

		const secondary = can_write
			? (next.secondary || []).map((a) => this.button(a, "btn-default")).join("")
			: "";
		const history = guide.platform
			? `<details class="si-guide-history"><summary>${__(
					"Platform history"
			  )}</summary><div class="si-guide-history-body"></div></details>`
			: "";

		$wrapper.html(`<div class="si-guide">
				<div class="si-guide-top">
					<span class="si-guide-platform">${platform_line}</span>
					<span class="si-guide-acts">
						<button class="btn btn-xs btn-link" data-si-toggle="collapse" aria-expanded="true">${__(
							"Collapse"
						)} ▴</button>
					</span>
				</div>
				${history}
				<ol class="si-guide-steps" aria-label="${__("Progress")}">${this.steps(guide.steps)}</ol>
				<div class="si-guide-next tone-${esc(next.tone || "blue")}" aria-live="polite">
					<div class="si-guide-eyebrow">${__("Next step")}</div>
					<h4>${esc(next.title || "")}</h4>
					${next.why ? `<p>${esc(next.why)}</p>` : ""}
					${next.note ? `<p class="si-guide-note">${esc(next.note)}</p>` : ""}
					${primary || secondary ? `<div class="si-guide-acts">${primary}${secondary}</div>` : ""}
				</div>
				<div class="si-guide-split">
					<section>
						<div class="si-guide-eyebrow">${__("Checks")}</div>
						<ul class="si-guide-checks">${this.checks(guide.checks, can_write)}</ul>
					</section>
					<section>
						<div class="si-guide-eyebrow">${__("Other options")}</div>
						<ul class="si-guide-options">${this.options(guide.options, can_write)}</ul>
					</section>
				</div>
			</div>`);

		if (guide.platform) {
			etransactions.lifecycle.render_history(
				frm,
				$wrapper.find(".si-guide-history-body"),
				guide.platform
			);
		}
		this.bind(frm, $wrapper);
	},

	GLYPHS: { done: "✓", warning: "!", error: "×", skipped: "–" },

	steps(steps) {
		const esc = frappe.utils.escape_html;
		return steps
			.map(
				(s, i) => `<li class="si-guide-step is-${esc(s.state)}">
					<span class="si-guide-dot" aria-hidden="true">${this.GLYPHS[s.state] || i + 1}</span>
					<span class="si-guide-step-label">${esc(s.label)}</span>
					<span class="si-guide-step-note">${esc(s.note || "")}</span>
				</li>`
			)
			.join("");
	},

	mini_steps(steps) {
		const esc = frappe.utils.escape_html;
		return steps
			.map((s) => {
				const note =
					["current", "warning"].includes(s.state) && s.note ? ` · ${esc(s.note)}` : "";
				return `<li class="is-${esc(
					s.state
				)}"><span class="si-guide-mdot" aria-hidden="true">${
					s.state === "done" ? "✓" : ""
				}</span>${esc(s.label)}${note}</li>`;
			})
			.join("");
	},

	CHECK_ICONS: { ok: "✓", warning: "!", todo: "•", error: "×" },

	checks(checks, can_write) {
		const esc = frappe.utils.escape_html;
		const states = {
			ok: __("Passed"),
			warning: __("Warning"),
			todo: __("To do"),
			error: __("To fix"),
		};
		return checks
			.map(
				(c) => `<li class="is-${esc(c.state)}">
					<span class="si-guide-icon" title="${esc(states[c.state])}">${this.CHECK_ICONS[c.state]}</span>
					<span class="si-guide-check-text">
						<span class="si-guide-check-label">${esc(c.label)}</span>
						${c.detail ? `<span class="si-guide-check-detail">${esc(c.detail)}</span>` : ""}
					</span>
					${can_write && c.action && c.state !== "ok" ? this.link(c.action) : "<span></span>"}
				</li>`
			)
			.join("");
	},

	options(options, can_write) {
		const esc = frappe.utils.escape_html;
		if (!options.length) return `<li class="text-muted">${__("No other option.")}</li>`;
		return options
			.map((o) => {
				const clickable = can_write && o.action && !o.disabled;
				const label = clickable
					? `<a href="#" class="${o.tone === "red" ? "text-danger" : ""}" ${this.data(
							o.action
					  )}>${esc(o.label)}</a>`
					: `<span>${esc(o.label)}</span>`;
				return `<li class="${o.disabled ? "is-disabled" : ""}">
						<div class="si-guide-option-head">${label}<span class="si-guide-tag">${esc(
					o.tag || ""
				)}</span></div>
						${o.description ? `<p>${esc(o.description)}</p>` : ""}
					</li>`;
			})
			.join("");
	},

	// --- Summary: header data read from the invoice -----------------------------------

	render_summary(frm, guide) {
		const $wrapper = frm.get_field("review_summary_html")?.$wrapper;
		if (!$wrapper) return;
		const esc = frappe.utils.escape_html;
		const doc = frm.doc;

		// Each field shows the worst check that is about it, as a hint under the value.
		const hints = {};
		const rank = { error: 3, todo: 2, warning: 1, ok: 0 };
		for (const c of guide.checks) {
			for (const f of c.fields || []) {
				if (!hints[f] || rank[c.state] > rank[hints[f].state]) hints[f] = c;
			}
		}

		const value = (df) => {
			const v = doc[df];
			if (v === undefined || v === null || v === "")
				return `<span class="text-muted">—</span>`;
			const meta = frappe.meta.get_docfield(doc.doctype, df, doc.name);
			return frappe.format(v, meta, { inline: true }, doc);
		};
		const row = (df, label) => {
			const hint = hints[df];
			const cls = hint && hint.state !== "ok" ? `is-${hint.state}` : "";
			const text = hint
				? hint.state === "ok"
					? hint.detail || hint.label
					: hint.label
				: "";
			return `<div class="si-fact ${cls}">
					<dt>${esc(label)}</dt>
					<dd>${value(df)}${
				text ? `<span class="si-fact-hint is-${esc(hint.state)}">${esc(text)}</span>` : ""
			}</dd>
				</div>`;
		};
		const amount = (v) => format_currency(v || 0, doc.currency);
		const net_differs =
			Math.abs(Math.abs(doc.net_total || 0) - Math.abs(doc.supplier_net_amount || 0)) >=
			0.005;
		const heading =
			{
				platform: __("Read from the e-invoice"),
				einvoice: __("Read from the e-invoice"),
				ocr: __("Read by OCR from the document"),
			}[guide.source] || __("Invoice data");

		$wrapper.html(`<div class="si-facts">
				<div class="si-facts-head">
					<span class="si-guide-eyebrow">${esc(heading)}</span>
					<a href="#" class="si-goto-details">${__("Edit in Details")} →</a>
				</div>
				<div class="si-facts-group">
					<div class="si-facts-title">${__("Supplier")}</div>
					<dl>
						${row("supplier", __("Supplier"))}
						${row("tax_id", __("Tax ID"))}
						${row("company", __("Company"))}
					</dl>
				</div>
				<div class="si-facts-group">
					<div class="si-facts-title">${__("Invoice")}</div>
					<dl>
						${row("bill_no", __("Supplier Invoice No"))}
						${row("bill_date", __("Invoice Date"))}
						${row("posting_date", __("Posting Date"))}
						${row("due_date", __("Due Date"))}
						${
							doc.purchase_order_number
								? row(
										"purchase_order_number",
										__("Order reference on the invoice")
								  )
								: ""
						}
						${row("currency", __("Currency"))}
					</dl>
				</div>
				<div class="si-facts-group">
					<div class="si-facts-title">${__("Amounts")} <span class="text-muted">${__(
			"supplier's figures and your lines"
		)}</span></div>
					<table class="si-amounts">
						<thead><tr><th></th><th>${__("Invoice")}</th><th>${__("Lines")}</th></tr></thead>
						<tbody>
							<tr class="${net_differs ? "is-diff" : ""}"><td>${__("Net Total")}</td><td>${amount(
			doc.supplier_net_amount
		)}</td><td>${amount(doc.net_total)}</td></tr>
							<tr><td>${__("Tax Total")}</td><td>${amount(doc.supplier_tax_amount)}</td><td>${amount(
			doc.tax_total
		)}</td></tr>
							<tr><td><strong>${__("Grand Total")}</strong></td><td><strong>${amount(
			doc.supplier_grand_total
		)}</strong></td><td><strong>${amount(doc.grand_total)}</strong></td></tr>
						</tbody>
					</table>
				</div>
			</div>`);

		$wrapper.find(".si-goto-details").on("click", (e) => {
			e.preventDefault();
			this.goto_field(frm, "supplier");
		});
	},

	// --- Lines -------------------------------------------------------------------------

	MATCH: {
		Learned: { tone: "green", label: __("Learned") },
		Confirmed: { tone: "blue", label: __("Confirmed") },
		Manual: { tone: "blue", label: __("Manual") },
		"From Order": { tone: "green", label: __("From the order") },
		Suggested: { tone: "orange", label: __("Suggested") },
	},

	render_lines(frm, guide) {
		const $wrapper = frm.get_field("review_lines_html")?.$wrapper;
		if (!$wrapper) return;
		const esc = frappe.utils.escape_html;
		const doc = frm.doc;
		const can_write =
			frm.perm[0] && frm.perm[0].write && !["Completed", "Closed"].includes(doc.status);
		const flagged = new Set();
		for (const c of guide.checks) {
			if (c.state !== "ok") (c.rows || []).forEach((r) => flagged.add(r));
		}

		const rows = (doc.items || [])
			.map((item) => {
				const match = this.MATCH[item.item_match];
				let match_html = match
					? `<span class="indicator-pill ${match.tone} no-indicator-dot">${esc(
							match.label
					  )}</span>`
					: "";
				if (!item.item_code) {
					match_html = `<span class="indicator-pill red no-indicator-dot">${__(
						"To match"
					)}</span>`;
				}
				if (can_write && item.item_code && item.item_match === "Suggested") {
					match_html += ` <a href="#" data-si-action="confirm_items" data-si-row="${
						item.idx
					}">${__("Confirm")}</a>`;
				}
				const item_html = item.item_code
					? `<span class="si-line-item">${esc(item.item_code)}</span>${
							can_write
								? ` <a href="#" class="si-line-change" data-si-action="pick_item" data-si-row="${
										item.idx
								  }">${__("Change")}</a>`
								: ""
					  }`
					: can_write
					? `<button class="btn btn-xs btn-default" data-si-action="pick_item" data-si-row="${
							item.idx
					  }">${__("Choose item")}</button>`
					: `<span class="text-muted">—</span>`;
				const order = item.reference_docname
					? `<a href="/app/${frappe.router.slug(
							item.reference_doctype
					  )}/${encodeURIComponent(item.reference_docname)}">${esc(
							item.reference_docname
					  )}</a>`
					: guide.order_required
					? `<span class="text-muted">${__("Not linked")}</span>`
					: `<span class="text-muted">—</span>`;
				const code = item.supplier_item_code
					? `<small>${esc(__("Ref. {0}", [item.supplier_item_code]))}</small>`
					: "";
				return `<tr class="${flagged.has(item.idx) ? "is-flagged" : ""}">
						<td>${item.idx}</td>
						<td class="si-line-desc">${esc(
							item.supplier_description || strip_html(item.description || "")
						)}${code}</td>
						<td class="text-right">${format_number(item.qty)}</td>
						<td class="text-right">${format_currency(item.amount, doc.currency)}</td>
						<td>${item_html}</td>
						<td>${match_html}</td>
						<td>${order}</td>
					</tr>`;
			})
			.join("");

		const order_help = guide.order_required
			? guide.order_doctype === "Purchase Receipt"
				? __(
						"<b>Order</b> links the line to the goods you received. You then pay only for what was delivered, and the receipt shows as billed. Your settings require it for every line."
				  )
				: __(
						"<b>Order</b> links the line to what you ordered. You then pay only for what you ordered, and the order shows as billed. Your settings require it for every line."
				  )
			: __("<b>Order</b> is optional with your settings. Link one to see it as billed.");

		const link_button =
			can_write && !doc.is_return
				? `<button class="btn btn-xs btn-default" data-si-action="select_orders" data-si-doctype="${esc(
						guide.order_doctype
				  )}">${
						guide.order_doctype === "Purchase Receipt"
							? __("Link to a receipt…")
							: __("Link to an order…")
				  }</button>`
				: "";

		$wrapper.html(`<div class="si-lines">
				<div class="si-lines-head">
					<span class="si-guide-eyebrow">${__("Invoice lines ({0})", [(doc.items || []).length])}</span>
					${link_button}
				</div>
				<div class="si-lines-help">
					${__(
						"<b>Your item</b> tells Dokos which product and expense account to book each supplier line to. What you confirm is remembered for this supplier's next invoices."
					)}
					${order_help}
				</div>
				<div class="si-lines-table">
					<table class="table table-sm">
						<thead><tr>
							<th>#</th><th>${__("Supplier line")}</th><th class="text-right">${__("Qty")}</th>
							<th class="text-right">${__("Amount")}</th><th>${__("Your item")}</th>
							<th>${__("Match", null, "Item match column")}</th><th>${__("Order")}</th>
						</tr></thead>
						<tbody>${rows || `<tr><td colspan="7" class="text-muted">${__("No lines yet.")}</td></tr>`}</tbody>
					</table>
				</div>
			</div>`);
		this.bind(frm, $wrapper);
	},

	// --- Actions -----------------------------------------------------------------------

	data(a) {
		const esc = frappe.utils.escape_html;
		const extra = ["field", "row", "doctype", "name", "status", "submit"]
			.filter((k) => a[k] !== undefined && a[k] !== null)
			.map((k) => `data-si-${k}="${esc(String(a[k]))}"`)
			.join(" ");
		return `data-si-action="${esc(a.action)}" ${extra}`;
	},

	button(a, cls) {
		return `<button class="btn btn-sm ${cls}" ${this.data(a)}>${frappe.utils.escape_html(
			a.label
		)}</button>`;
	},

	link(a) {
		return `<a href="#" class="si-guide-fix" ${this.data(a)}>${frappe.utils.escape_html(
			a.label
		)} →</a>`;
	},

	bind(frm, $wrapper) {
		$wrapper.find("[data-si-toggle]").on("click", (e) => {
			e.preventDefault();
			this.set_collapsed(frm, $(e.currentTarget).attr("data-si-toggle") === "collapse");
		});
		$wrapper.find("[data-si-action]").on("click", (e) => {
			e.preventDefault();
			const d = $(e.currentTarget).data();
			this.run(frm, {
				action: d.siAction,
				field: d.siField,
				row: d.siRow,
				doctype: d.siDoctype,
				name: d.siName,
				status: d.siStatus,
				submit: d.siSubmit,
			});
		});
	},

	run(frm, a) {
		const handlers = {
			goto_field: () => this.goto_field(frm, a.field),
			create_supplier: () => frm.trigger("create_supplier"),
			pick_item: () => this.pick_item(frm, a.row),
			confirm_items: () => this.confirm_items(frm, a.row),
			select_orders: () => new etransactions.PurchaseDocumentSelector(frm, a.doctype),
			link_order: () => this.link_order(frm, a.doctype, a.name),
			create_purchase_order: () => etransactions.supplier_invoice.create_po_pi(frm),
			create_purchase_invoice: () =>
				etransactions.supplier_invoice.create_purchase_invoice(frm, !!cint(a.submit)),
			allocate_credit_note: () =>
				etransactions.supplier_invoice.open_credit_note_allocation_dialog(frm),
			open_doc: () => frappe.set_route("Form", a.doctype, a.name),
			record_payment: () => this.record_payment(a.name),
			retry_download: () => this.retry_download(frm),
			report_status: () => this.report_status(frm, a.status),
			close: () => frm.call("close_request").then(() => frm.reload_doc()),
			reopen: () => frm.call("open_request").then(() => frm.reload_doc()),
		};
		const handler = handlers[a.action];
		if (!handler) return;
		// Most actions work on the saved invoice: save pending edits first.
		const needs_save = !["goto_field", "pick_item", "open_doc", "report_status"].includes(
			a.action
		);
		if (needs_save && frm.is_dirty()) {
			frm.save().then(handler);
		} else {
			handler();
		}
	},

	goto_field(frm, fieldname) {
		const field = frm.get_field(fieldname);
		if (field?.tab) field.tab.set_active();
		frm.scroll_to_field(fieldname);
	},

	pick_item(frm, idx) {
		const item = (frm.doc.items || []).find((i) => i.idx === cint(idx));
		if (!item) return;
		const dialog = new frappe.ui.Dialog({
			title: __("Choose the item for line {0}", [item.idx]),
			fields: [
				{
					fieldtype: "HTML",
					fieldname: "line",
					options: `<p class="text-muted">${frappe.utils.escape_html(
						item.supplier_description || ""
					)}</p>`,
				},
				{
					fieldtype: "Link",
					fieldname: "item_code",
					label: __("Item"),
					options: "Item",
					reqd: 1,
					default: item.item_code,
					get_query: () => ({
						query: "erpnext.controllers.queries.item_query",
						filters: { is_purchase_item: 1, has_variants: 0 },
					}),
				},
			],
			primary_action_label: __("Save"),
			primary_action: async ({ item_code }) => {
				dialog.hide();
				await frappe.model.set_value(item.doctype, item.name, "item_code", item_code);
				// Let the item_code handler fetch the account and tax template before saving.
				await etransactions.supplier_invoice.fetch_item_details(
					frm,
					item.doctype,
					item.name
				);
				frm.save();
			},
		});
		dialog.show();
	},

	confirm_items(frm, idx) {
		const rows = (frm.doc.items || []).filter(
			(i) => i.item_match === "Suggested" && i.item_code && (!idx || i.idx === cint(idx))
		);
		rows.forEach((i) => frappe.model.set_value(i.doctype, i.name, "item_match", "Confirmed"));
		if (rows.length) frm.save();
	},

	link_order(frm, doctype, name) {
		frm.call("link_purchase_document", { doctype, name }).then((r) => {
			frm.reload_doc();
			const res = r.message || {};
			const message =
				res.unlinked && res.unlinked.length
					? __(
							"{0} line(s) linked to {1}. Line(s) {2} have no matching item on it: link them by hand.",
							[res.linked, name, res.unlinked.join(", ")]
					  )
					: __("All lines linked to {0}.", [name]);
			frappe.show_alert({
				message,
				indicator: res.unlinked && res.unlinked.length ? "orange" : "green",
			});
		});
	},

	record_payment(purchase_invoice) {
		frappe
			.xcall("erpnext.accounts.doctype.payment_entry.payment_entry.get_payment_entry", {
				dt: "Purchase Invoice",
				dn: purchase_invoice,
			})
			.then((doc) => {
				const synced = frappe.model.sync(doc);
				frappe.set_route("Form", synced[0].doctype, synced[0].name);
			});
	},

	retry_download(frm) {
		frappe
			.call({
				method: "etransactions.etransactions.doctype.einvoice.einvoice.retry_einvoice_content_fetch",
				args: { einvoice: frm.doc.einvoice },
				freeze: true,
			})
			.then((r) => {
				if (r.exc) return;
				frappe.show_alert({
					message: __("Download queued. Reload the invoice in a moment."),
					indicator: "blue",
				});
			});
	},

	report_status(frm, status) {
		const def = ((frm._si_guide?.platform || {}).actions || []).find(
			(a) => a.status === status
		);
		if (def) etransactions.lifecycle.send_status(frm, def);
	},
};
