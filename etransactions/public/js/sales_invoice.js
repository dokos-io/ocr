// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (frm.doc.docstatus === 1 && frm.doc.etransaction_profile) {
			frm.add_custom_button(__("Download FacturX Invoice"), () => {
				frappe.call({
					method: "etransactions.overrides.sales_invoice.get_facturx_pdf",
					args: { sales_invoice: frm.doc.name },
					freeze: true,
					freeze_message: __("Generating FacturX PDF…"),
					callback(r) {
						if (r.message) window.open(r.message);
					},
				});
			}, __("eInvoice"));

			_refresh_einvoice_status(frm);
			_add_pa_buttons(frm);
		}

		if (frm.doc.docstatus === 0 && frm.doc.etransaction_profile && !frm.is_new()) {
			_refresh_einvoice_status(frm);
		}
	},

	after_save(frm) {
		if (frm.doc.docstatus === 0 && frm.doc.etransaction_profile) {
			_refresh_einvoice_status(frm);
		}
	},
});

function _refresh_einvoice_status(frm) {
	frappe.call({
		method: "etransactions.overrides.sales_invoice.get_einvoice_status",
		args: { sales_invoice: frm.doc.name },
		callback(r) {
			const data = r.message;

			if (!data || !data.einvoice) {
				_render_status(frm, "gray", __("No eInvoice generated yet."), null, true);
				return;
			}

			const { einvoice, errors, warnings, has_iban } = data;

			if (errors) {
				_render_status(frm, "red", errors, einvoice, has_iban);
			} else if (warnings || !has_iban) {
				_render_status(frm, "orange", warnings, einvoice, has_iban);
			} else {
				_render_status(frm, "green", "", einvoice, has_iban);
			}
		},
	});
}

function _add_pa_buttons(frm) {
	frappe.call({
		method: "etransactions.overrides.sales_invoice.get_einvoice_status",
		args: { sales_invoice: frm.doc.name },
		callback(r) {
			const data = r.message;
			if (!data || !data.einvoice) return;

			const pa_status = data.pa_status;
			const pa_flow_id = data.pa_flow_id;

			if (!pa_flow_id || ["created", ""].includes(pa_status || "")) {
				frm.add_custom_button(__("Send to Plateforme Agréée"), () => {
					frappe.call({
						method: "etransactions.overrides.sales_invoice.send_to_plateforme",
						args: { sales_invoice: frm.doc.name },
						freeze: true,
						freeze_message: __("Submitting to Plateforme Agréée…"),
						callback() {
							frm.reload_doc();
						},
					});
				}, __("Plateforme Agréée"));
			}

			if (pa_flow_id) {
				frm.add_custom_button(__("Refresh PA Status"), () => {
					frappe.call({
						method: "etransactions.overrides.sales_invoice.refresh_pa_status",
						args: { sales_invoice: frm.doc.name },
						freeze: true,
						freeze_message: __("Refreshing status…"),
						callback() {
							frm.reload_doc();
						},
					});
				}, __("Plateforme Agréée"));
			}
		},
	});
}

function _render_status(frm, color, message, einvoice_name, has_iban) {
	const field = frm.fields_dict.etransactions_status_html;
	if (!field) return;

	const wrapper = document.createElement("div");
	wrapper.style.padding = "8px 0";

	const pill = document.createElement("span");
	pill.className = `indicator-pill ${color}`;

	const labels = { green: __("eInvoice valid"), orange: __("eInvoice warnings"), red: __("eInvoice errors"), gray: __("eInvoice pending") };
	pill.textContent = labels[color] || color;
	wrapper.appendChild(pill);

	const lines = (message || "").split("\n").filter(Boolean);
	if (lines.length) {
		const ul = document.createElement("ul");
		ul.style.cssText = "font-size:var(--text-sm);color:var(--text-muted);margin:6px 0 4px 16px;";
		lines.slice(0, 5).forEach(line => {
			const li = document.createElement("li");
			li.textContent = line;
			ul.appendChild(li);
		});
		if (lines.length > 5) {
			const li = document.createElement("li");
			li.textContent = __("{0} more…", [lines.length - 5]);
			ul.appendChild(li);
		}
		wrapper.appendChild(ul);
	}

	if (!has_iban) {
		const hint = document.createElement("div");
		hint.style.cssText = "font-size:var(--text-sm);color:var(--text-muted);margin-top:4px;";
		const link = document.createElement("a");
		link.href = "/app/bank-account";
		link.textContent = __("Set up payment IBAN →");
		hint.appendChild(document.createTextNode(__("No payment IBAN configured.") + " "));
		hint.appendChild(link);
		wrapper.appendChild(hint);
	}

	if (einvoice_name) {
		const nav = document.createElement("div");
		nav.style.cssText = "font-size:var(--text-sm);margin-top:6px;";
		const link = document.createElement("a");
		link.href = frappe.utils.get_form_link("eInvoice", einvoice_name);
		link.textContent = __("Open eInvoice →");
		nav.appendChild(link);
		wrapper.appendChild(nav);
	}

	field.wrapper.innerHTML = "";
	field.wrapper.appendChild(wrapper);
}
