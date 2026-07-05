// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		// B2C / foreign sales are e-reported (no structured profile), so show
		// their PPF e-reporting status independently of the e-invoice profile.
		if (frm.doc.docstatus === 1) _show_ereporting(frm);

		// The readiness panel runs even without a profile (it flags the missing
		// profile itself); the eInvoice buttons only make sense with one.
		etransactions.invoiceReadiness.refresh(frm);

		if (!frm.doc.etransaction_profile) return;

		if (frm.doc.docstatus === 1) {
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

			_add_pa_buttons(frm);
			_attach_lifecycle(frm);
		}
	},

	etransaction_profile: (frm) => etransactions.invoiceReadiness.refresh(frm),
	customer: (frm) => etransactions.invoiceReadiness.refresh(frm),
	customer_address: (frm) => etransactions.invoiceReadiness.refresh(frm),
	company: (frm) => etransactions.invoiceReadiness.refresh(frm),
	company_address: (frm) => etransactions.invoiceReadiness.refresh(frm),
	po_no: (frm) => etransactions.invoiceReadiness.refresh(frm),
	after_save: (frm) => etransactions.invoiceReadiness.refresh(frm),

	before_submit(frm) {
		if (!frm.doc.etransaction_profile) return;
		return etransactions.invoiceReadiness.gate(frm);
	},

	before_cancel(frm) {
		// An invoice already transmitted to the accredited platform must report
		// the "Cancelled" lifecycle status first — the server hook blocks a direct
		// cancel, so route through the guided endpoint after confirmation.
		if (!frm.doc.etransaction_profile) return;
		return new Promise((resolve, reject) => {
			frappe
				.call({
					method: "etransactions.overrides.sales_invoice.get_einvoice_status",
					args: { sales_invoice: frm.doc.name },
				})
				.then((r) => {
					const d = r.message || {};
					const live = d.pa_flow_id && !["error", "rejected"].includes(d.pa_status || "");
					if (!live) {
						resolve();
						return;
					}
					frappe.confirm(
						__(
							"This invoice was transmitted to the accredited platform (flow {0}).<br>" +
								"The <b>Cancelled</b> lifecycle status will be reported to the platform, " +
								"then the invoice will be cancelled. Continue?",
							[frappe.utils.escape_html(d.pa_flow_id)]
						),
						() => {
							frappe
								.call({
									method: "etransactions.overrides.sales_invoice.cancel_with_lifecycle",
									args: { sales_invoice: frm.doc.name },
									freeze: true,
									freeze_message: __("Reporting the cancellation to the platform…"),
								})
								.then(() => {
									frm.reload_doc();
									// The server endpoint already cancelled the document.
									reject();
								})
								.catch(reject);
						},
						() => reject()
					);
				})
				.catch(() => resolve());
		});
	},
});

frappe.ui.form.on("Sales Taxes and Charges", {
	charge_type: (frm) => etransactions.invoiceReadiness.refresh(frm),
	taxes_remove: (frm) => etransactions.invoiceReadiness.refresh(frm),
});

function _show_ereporting(frm) {
	frappe.call({
		method: "etransactions.plateforme_agreee.ereporting.get_source_ereporting",
		args: { doctype: frm.doctype, name: frm.doc.name },
		callback(r) {
			const e = r.message;
			if (!e || !e.name) return;
			const colors = { pending: "orange", sent: "blue", error: "red" };
			frm.dashboard.add_indicator(
				__("PPF e-reporting: {0}", [e.state]),
				colors[e.state] || "gray"
			);
		},
	});
}

function _attach_lifecycle(frm) {
	frappe.call({
		method: "etransactions.etransactions.doctype.einvoice.einvoice.get_transaction_einvoice",
		args: { doctype: frm.doctype, name: frm.doc.name },
		callback(r) {
			if (r.message) {
				etransactions.lifecycle.attach(frm, {
					einvoice: r.message.name,
					side: r.message.side,
					pa_status: r.message.pa_status,
				});
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

			// At-a-glance platform status on the dashboard.
			if (pa_status) {
				const colors = {
					rejected: "red",
					error: "red",
					done: "green",
					pending: "blue",
					sent: "blue",
					created: "gray",
				};
				frm.dashboard.add_indicator(
					__("e-invoice: {0}", [pa_status]),
					colors[pa_status] || "gray"
				);
			}

			if (!pa_flow_id || ["created", "", "error", "rejected"].includes(pa_status || "")) {
				frm.add_custom_button(__("Send to the accredited platform"), () => {
					const send = () => {
						frappe.call({
							method: "etransactions.overrides.sales_invoice.send_to_plateform",
							args: { sales_invoice: frm.doc.name },
							freeze: true,
							freeze_message: __("Submitting to accredited platform…"),
							callback() {
								frm.reload_doc();
							},
						});
					};
					if (pa_status === "error" || pa_status === "rejected") {
						// Show the previous rejection reasons so the user can confirm
						// they've been addressed before resending.
						frappe.call({
							method: "etransactions.overrides.sales_invoice.get_einvoice_panel",
							args: { sales_invoice: frm.doc.name },
							callback(p) {
								const reasons = ((p.message || {}).problems || []).map(
									(f) => `<li>${frappe.utils.escape_html(f.label)}</li>`
								).join("");
								frappe.confirm(
									`${__("The previous submission was rejected by the accredited platform:")}
									${reasons ? `<ul style="margin-top:8px">${reasons}</ul>` : ""}
									${__("Send this e-invoice again?")}`,
									send
								);
							},
						});
					} else {
						send();
					}
				}, __("Accredited platform"));
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
				}, __("Accredited platform"));
			}
		},
	});
}
