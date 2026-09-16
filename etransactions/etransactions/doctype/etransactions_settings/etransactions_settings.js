// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("eTransactions Settings", {
	refresh(frm) {
		_render_platform_management(frm);
	},

	enable_einvoicing(frm) {
		// The flag is read into frappe.boot at page load, so open forms only
		// reflect the change after a reload.
		frappe.show_alert({
			message: __("Reload your open forms for this change to take effect."),
			indicator: "blue",
		});
	},
});

function _render_platform_management(frm) {
	const $wrapper = frm.fields_dict.platform_html.$wrapper;
	// `refresh` fires many times per form life; the wrapper is a stable element,
	// so clear our namespaced delegated handlers before re-binding to avoid
	// stacking one listener (and thus one dialog) per refresh.
	$wrapper.off(".etplatform");
	$wrapper.empty();

	$wrapper.append(`
		<div class="et-platform-mgmt">
			<div class="et-platform-actions">
				<button class="btn btn-sm btn-primary" id="btn-add-superpdp">
					${frappe.utils.icon("add")} SuperPDP
				</button>
				<button class="btn btn-sm btn-primary" id="btn-add-esalink">
					${frappe.utils.icon("add")} Esalink
				</button>
				<button class="btn btn-sm btn-default" id="btn-add-custom">
					${frappe.utils.icon("add")} ${__("Custom Platform")}
				</button>
			</div>
			<div id="platform-table-container">
				<div class="text-muted text-center" id="loading-msg">
					${frappe.utils.icon("loading-indicator")} ${__("Loading…")}
				</div>
			</div>
		</div>
	`);

	_load_platforms(frm);

	$wrapper.on("click.etplatform", "#btn-add-superpdp", () => _open_platform_dialog(frm, null, "SuperPDP"));
	$wrapper.on("click.etplatform", "#btn-add-esalink", () => _open_platform_dialog(frm, null, "Esalink"));
	$wrapper.on("click.etplatform", "#btn-add-custom", () => _open_platform_dialog(frm, null, "Custom"));

	$wrapper.on("click.etplatform", ".btn-edit-platform", function () {
		_open_platform_dialog(frm, $(this).data("name"));
	});

	$wrapper.on("click.etplatform", ".btn-toggle-platform", function () {
		const name = $(this).data("name");
		const is_active = $(this).data("active") ? 0 : 1;
		frappe.confirm(
			is_active ? __("Activate this platform?") : __("Deactivate this platform?"),
			() => {
				frappe.call({
					method: "etransactions.etransactions.doctype.etransactions_accredited_platform.etransactions_accredited_platform.toggle_active",
					args: { platform_name: name, is_active },
					callback: (r) => {
						if (!r.exc) {
							frappe.show_alert({ message: is_active ? __("Platform activated") : __("Platform deactivated"), indicator: "green" });
							_load_platforms(frm);
						}
					},
				});
			}
		);
	});

	$wrapper.on("click.etplatform", ".btn-test-platform", function () {
		const name = $(this).data("name");
		frappe.call({
			method: "etransactions.plateforme_agreee.session.run_platform_health_check",
			args: { platform_name: name },
			freeze: true,
			freeze_message: __("Testing connection…"),
			callback: (r) => {
				const res = r.message || {};
				frappe.show_alert({
					message: res.message || etransactions.status_labels.health(res.status),
					indicator: res.status === "ok" ? "green" : "red",
				});
				_load_platforms(frm);
			},
		});
	});

	$wrapper.on("click.etplatform", ".btn-delete-platform", function () {
		const name = $(this).data("name");
		frappe.confirm(__("Delete this platform? This cannot be undone."), () => {
			frappe.call({
				method: "etransactions.etransactions.doctype.etransactions_accredited_platform.etransactions_accredited_platform.delete_platform",
				args: { platform_name: name },
				freeze: true,
				freeze_message: __("Deleting…"),
				callback: (r) => {
					if (!r.exc) {
						frappe.show_alert({ message: __("Platform deleted"), indicator: "green" });
						_load_platforms(frm);
					}
				},
			});
		});
	});
}

function _load_platforms(frm) {
	frappe.call({
		method: "etransactions.etransactions.doctype.etransactions_accredited_platform.etransactions_accredited_platform.get_platforms",
		callback: (r) => {
			if (!r.exc) _render_platform_table(frm, r.message || []);
		},
	});
}

function _render_platform_table(frm, platforms) {
	const $container = frm.fields_dict.platform_html.$wrapper.find("#platform-table-container");

	if (!platforms.length) {
		$container.html(`<div class="et-platform-empty">${__("No accredited platforms configured. Use the buttons above to add one.")}</div>`);
		return;
	}

	const TYPE_BADGE_MOD = {
		SuperPDP: "et-type-badge--superpdp",
		Esalink: "et-type-badge--esalink",
		Custom: "et-type-badge--custom",
	};
	const TX_LABEL = { Both: __("Sales + Purchases"), Sales: __("Sales"), Purchases: __("Purchases") };
	const HEALTH = {
		ok: ["green", __("Connected")],
		error: ["red", __("Error")],
		unknown: ["gray", __("Not tested")],
	};

	let rows = "";
	platforms.forEach((p) => {
		// An Esalink platform with no minted customer account is not registered yet — surface
		// that instead of an "Inactive" badge, and hide the Test button (probing an
		// unprovisioned account returns a red health pill that reads as a misconfiguration).
		const unregistered_esalink = p.platform_type === "Esalink" && !p.esalink_customer_id;
		const active_badge = unregistered_esalink
			? `<span class="indicator-pill orange">${__("Not registered")}</span>`
			: p.is_active
			? `<span class="indicator-pill green">${__("Active")}</span>`
			: `<span class="indicator-pill gray">${__("Inactive")}</span>`;
		const [health_color, health_label] = HEALTH[p.last_health_status || "unknown"] || HEALTH.unknown;
		const health_title = p.last_health_check
			? __("Last checked: {0}", [frappe.datetime.str_to_user(p.last_health_check)]) + (p.last_health_message ? " — " + frappe.utils.escape_html(p.last_health_message) : "")
			: __("Connection not tested yet");
		const health_badge = `<span class="indicator-pill ${health_color}" title="${health_title}">${health_label}</span>`;
		const type_badge = `<span class="et-type-badge ${TYPE_BADGE_MOD[p.platform_type] || "et-type-badge--custom"}">${frappe.utils.escape_html(p.platform_type)}</span>`;
		const tx_label = TX_LABEL[p.transaction_type] || frappe.utils.escape_html(p.transaction_type);
		const toggle_mod = p.is_active ? "et-icon-btn--deactivate" : "et-icon-btn--activate";
		const toggle_icon = p.is_active ? frappe.utils.icon("solid-error") : frappe.utils.icon("check");
		const toggle_title = p.is_active ? __("Deactivate") : __("Activate");

		rows += `
			<tr>
				<td><span class="et-platform-name">${frappe.utils.escape_html(p.platform_name)}</span></td>
				<td>${type_badge}</td>
				<td>${frappe.utils.escape_html(p.company)}</td>
				<td>${tx_label}</td>
				<td><span class="et-platform-code">${frappe.utils.escape_html(p.platform_code)}</span></td>
				<td>${active_badge}</td>
				<td>${health_badge}</td>
				<td>
					<div class="et-btn-group">
						${
							unregistered_esalink
								? ""
								: `<button class="et-icon-btn btn-test-platform" data-name="${p.name}" title="${__("Test connection")}">
							${frappe.utils.icon("refresh")}
						</button>`
						}
						<button class="et-icon-btn btn-edit-platform" data-name="${p.name}" title="${__("Edit")}">
							${frappe.utils.icon("edit")}
						</button>
						<button class="et-icon-btn ${toggle_mod} btn-toggle-platform" data-name="${p.name}" data-active="${p.is_active ? 1 : 0}" title="${toggle_title}">
							${toggle_icon}
						</button>
						<button class="et-icon-btn et-icon-btn--danger btn-delete-platform" data-name="${p.name}" title="${__("Delete")}">
							${frappe.utils.icon("delete")}
						</button>
					</div>
				</td>
			</tr>`;
	});

	const html = `
		<div class="et-platform-table-wrap">
			<table class="et-platform-table">
				<thead>
					<tr>
						<th>${__("Platform")}</th>
						<th>${__("Type")}</th>
						<th>${__("Company")}</th>
						<th>${__("Transactions")}</th>
						<th>${__("Code")}</th>
						<th>${__("Status")}</th>
						<th>${__("Health")}</th>
						<th>${__("Actions")}</th>
					</tr>
				</thead>
				<tbody>${rows}</tbody>
			</table>
		</div>`;
	$container.html(html);
}

function _open_platform_dialog(frm, existing_name = null, preset_type = null) {
	const is_edit = !!existing_name;
	// Esalink registration is a separate flow (the "Register on Esalink" button in the status
	// banner); this dialog only edits the platform config record.

	const dialog = new frappe.ui.Dialog({
		title: is_edit ? __("Edit Accredited Platform") : __("Add Accredited Platform"),
		size: "large",
		fields: [
			{
				fieldtype: "Select",
				fieldname: "platform_type",
				label: __("Platform Type"),
				options: "Custom\nSuperPDP\nEsalink",
				reqd: 1,
				default: preset_type || "Custom",
				description: __("SuperPDP and Esalink have pre-configured setup flows."),
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Select",
				fieldname: "transaction_type",
				label: __("Transaction Type"),
				options: "Both\nSales\nPurchases",
				reqd: 1,
				default: "Both",
				description: __("Which transaction type this platform handles."),
			},
			{ fieldtype: "Section Break", label: __("Platform Details") },
			{
				fieldtype: "Data",
				fieldname: "platform_name",
				label: __("Platform Name"),
				reqd: 1,
			},
			{
				fieldtype: "Data",
				fieldname: "platform_code",
				label: __("Platform Code"),
				reqd: 1,
				depends_on: "eval:doc.platform_type === 'Custom'",
				description: __("Technical identifier sent to the API. Auto-set for SuperPDP and Esalink."),
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Link",
				fieldname: "company",
				label: __("Company"),
				options: "Company",
				reqd: 1,
			},
			{
				fieldtype: "Check",
				fieldname: "is_active",
				label: __("Active"),
				default: 1,
			},
			{
				fieldtype: "Section Break",
				label: __("Credentials"),
				depends_on: "eval:doc.platform_type !== 'Esalink'",
			},
			{
				fieldtype: "HTML",
				fieldname: "redirect_url_html",
				hidden: 1,
			},
			{
				fieldtype: "Password",
				fieldname: "client_id",
				label: __("Client ID"),
				depends_on: "eval:doc.platform_type !== 'Esalink'",
			},
			{
				fieldtype: "Password",
				fieldname: "client_secret",
				label: __("Client Secret"),
				depends_on: "eval:doc.platform_type !== 'Esalink'",
			},
			{ fieldtype: "HTML", fieldname: "test_result_html" },
			// --- Esalink account (registration is a separate flow — see the status banner) ---
			{
				fieldtype: "Section Break",
				fieldname: "esalink_reg_section",
				label: __("Esalink Account"),
				depends_on: "eval:doc.platform_type === 'Esalink'",
			},
			{ fieldtype: "HTML", fieldname: "esalink_status_html" },
			{ fieldtype: "Section Break", label: __("Options"), collapsible: 1 },
			{
				fieldtype: "Check",
				fieldname: "auto_send_on_submit",
				label: __("Send to Platform on Sales Invoice Submit"),
				default: 0,
			},
			{
				fieldtype: "Check",
				fieldname: "is_sandbox",
				label: __("Pre-production (Sandbox)"),
				default: 0,
				depends_on: "eval:doc.platform_type === 'SuperPDP'",
				description: __("Disables SuperPDP pre-validation checks (disable_pre_check) for test/pré-production environments."),
			},
			{
				fieldtype: "Int",
				fieldname: "directory_refresh_days",
				label: __("Directory Refresh (days)"),
				default: 15,
			},
			{
				fieldtype: "Data",
				fieldname: "api_base_url",
				label: __("Custom API Base URL"),
				depends_on: "eval:doc.platform_type === 'Custom'",
			},
			{
				fieldtype: "Select",
				fieldname: "esalink_environment",
				label: __("Esalink Environment"),
				options: "test\nprod",
				default: "prod",
				depends_on: "eval:doc.platform_type === 'Esalink'",
				description: __("prod = https://hubtimize.fr, test = https://ppd.hubtimize.fr (pré-production)."),
			},
		],
		primary_action_label: is_edit ? __("Update") : __("Create"),
		primary_action(values) {
			// Force the right platform_code for pre-defined types
			if (values.platform_type === "SuperPDP") values.platform_code = "superpdp";
			else if (values.platform_type === "Esalink") values.platform_code = "esalink";

			// A new Esalink row is created unregistered (registration is a separate flow
			// started from the Edit dialog), so it must not appear active.
			if (values.platform_type === "Esalink" && !is_edit) values.is_active = 0;

			frappe.call({
				method: "etransactions.etransactions.doctype.etransactions_accredited_platform.etransactions_accredited_platform.save_platform",
				args: { platform_data: values, existing_name: existing_name || null },
				freeze: true,
				freeze_message: is_edit ? __("Updating…") : __("Creating…"),
				callback(r) {
					if (!r.exc) {
						dialog.hide();
						frappe.show_alert({ message: is_edit ? __("Platform updated") : __("Platform created"), indicator: "green" });
						_load_platforms(frm);
					}
				},
			});
		},
	});

	function _toggle_redirect_url(type) {
		const is_superpdp = type === "SuperPDP";
		dialog.set_df_property("redirect_url_html", "hidden", !is_superpdp);
		if (!is_superpdp) return;

		const redirect_url = `${window.location.origin}/api/method/etransactions.plateforme_agreee.session.oauth_callback`;
		dialog.fields_dict.redirect_url_html.$wrapper.html(`
			<div class="form-group" style="margin-bottom: 8px;">
				<label class="control-label text-muted small">${__("Redirect URL — copy into the SuperPDP application registration form")}</label>
				<div class="input-group">
					<input type="text" class="form-control" readonly value="${redirect_url}" style="font-size: 12px;">
					<span class="input-group-btn">
						<button class="btn btn-default btn-sm et-copy-redirect-url">${__("Copy")}</button>
					</span>
				</div>
			</div>`);
		dialog.fields_dict.redirect_url_html.$wrapper.find(".et-copy-redirect-url").on("click", () => {
			navigator.clipboard.writeText(redirect_url);
			frappe.show_alert({ message: __("Copied!"), indicator: "green" });
		});
	}

	// Hard-block the dialog when Esalink is selected but the site has no partner
	// credentials in site_config. Renders a blocking banner and disables the primary
	// action until the credentials are configured; other platform types stay enabled.
	function _apply_esalink_partner_gate() {
		// Only new Esalink rows are hard-blocked; existing rows stay editable even if the
		// keys are later removed (mirrors the server-side is_new() guard).
		if (is_edit || dialog.get_value("platform_type") !== "Esalink") {
			dialog.enable_primary_action();
			_render_esalink_status();
			return;
		}
		frappe
			.xcall("etransactions.plateforme_agreee.esalink_provisioning.esalink_partner_status")
			.then((s) => {
				if (dialog.get_value("platform_type") !== "Esalink") return;
				if (s.configured) {
					dialog.enable_primary_action();
					_render_esalink_status();
					return;
				}
				dialog.disable_primary_action();
				dialog.fields_dict.esalink_status_html.$wrapper.html(`
					<div class="et-esalink-status">
						<div><span class="indicator-pill red">${__("Esalink not available")}</span></div>
						<div class="text-muted small" style="margin-top:6px">${frappe.utils.escape_html(s.message || "")}</div>
					</div>`);
			});
	}

	// Render the Esalink registration state into the status banner. In add mode there is no
	// record yet, so it explains registration is a separate later step; in edit mode it
	// fetches the account status and offers the register / manage actions.
	function _render_esalink_status() {
		const $html = dialog.fields_dict.esalink_status_html.$wrapper;
		if (dialog.get_value("platform_type") !== "Esalink") return;

		if (!is_edit) {
			$html.html(
				`<div class="text-muted small">${__(
					"This company will be added unregistered. Once the row is created, open it from the Edit button to register it on Esalink."
				)}</div>`
			);
			return;
		}

		$html.html(`<div class="text-muted small">${frappe.utils.icon("loading-indicator")} ${__("Checking Esalink registration…")}</div>`);
		frappe
			.xcall("etransactions.plateforme_agreee.esalink_provisioning.esalink_registration_status", { platform_name: existing_name })
			.then((s) => {
				if (s.registered) {
					const status_color = s.customer_status === "ACTIVE" ? "green" : "orange";
					const routing_address = `<code>${frappe.utils.escape_html(s.routing_address || "—")}</code>`;
					$html.html(`
						<div class="et-esalink-status" style="display:flex;flex-direction:column;gap:6px">
							<div>
								<span class="indicator-pill green">${__("Registered on Esalink")}</span>
								<span class="indicator-pill ${status_color}">${frappe.utils.escape_html(etransactions.status_labels.esalink_customer(s.customer_status))}</span>
							</div>
							<div class="text-muted small">${__("Customer: {0}", [frappe.utils.escape_html(s.customer_id || "—")])}</div>
							<div class="text-muted small">${__("Routing address: {0}", [routing_address])}</div>
							<div class="et-btn-group" style="margin-top:4px">
								<button class="btn btn-default btn-sm et-esalink-refresh">${__("Refresh status")}</button>
								<button class="btn btn-default btn-sm et-esalink-kyc">${__("Resend KYC email")}</button>
							</div>
						</div>`);
					$html.find(".et-esalink-refresh").on("click", () =>
						_esalink_manage_action("refresh_customer_status", __("Checking Esalink account status…"), _render_esalink_status)
					);
					$html.find(".et-esalink-kyc").on("click", () =>
						_esalink_manage_action("resend_kyc_email", __("Resending onboarding email…"))
					);
				} else {
					$html.html(`
						<div class="et-esalink-status" style="display:flex;flex-direction:column;gap:6px">
							<div><span class="indicator-pill orange">${__("Not registered on Esalink")}</span></div>
							<div class="text-muted small">${__(
								"This company has no Esalink account yet. Registering creates one, mints its API credentials and registers the routing address (SIREN)."
							)}</div>
							<div><button class="btn btn-primary btn-sm et-esalink-register">${__("Register on Esalink")}</button></div>
						</div>`);
					$html.find(".et-esalink-register").on("click", () =>
						_open_esalink_registration_dialog(frm, {
							platform_name: existing_name,
							company: dialog.get_value("company"),
							transaction_type: dialog.get_value("transaction_type"),
							on_done: () => {
								_render_esalink_status();
								_load_platforms(frm);
							},
						})
					);
				}
			})
			.catch(() => $html.empty());
	}

	// Shared handler for the Esalink manage buttons (refresh status / resend KYC email).
	function _esalink_manage_action(method, freeze_message, on_done) {
		frappe.call({
			method: `etransactions.plateforme_agreee.esalink_provisioning.${method}`,
			args: { platform_name: existing_name },
			freeze: true,
			freeze_message,
			callback(r) {
				if (r.exc) return;
				const res = r.message || {};
				frappe.show_alert({
					message: res.status ? __("Esalink status: {0}", [etransactions.status_labels.esalink_customer(res.status)]) : __("Done."),
					indicator: res.status === "ACTIVE" ? "green" : "blue",
				});
				if (on_done) on_done();
			},
		});
	}

	// Auto-fill platform_name suggestion and lock platform_code for pre-defined types
	dialog.fields_dict.platform_type.df.onchange = function () {
		const type = dialog.get_value("platform_type");
		const company = dialog.get_value("company") || "";
		if (type === "SuperPDP") {
			if (!dialog.get_value("platform_name")) {
				dialog.set_value("platform_name", company ? `SuperPDP - ${company}` : "SuperPDP");
			}
			dialog.set_df_property("platform_code", "read_only", 1);
			dialog.set_value("platform_code", "superpdp");
		} else if (type === "Esalink") {
			if (!dialog.get_value("platform_name")) {
				dialog.set_value("platform_name", company ? `Esalink - ${company}` : "Esalink");
			}
			dialog.set_df_property("platform_code", "read_only", 1);
			dialog.set_value("platform_code", "esalink");
		} else {
			dialog.set_df_property("platform_code", "read_only", 0);
			dialog.enable_primary_action();
		}
		_toggle_redirect_url(type);
		_apply_esalink_partner_gate();
	};

	// Reload the Esalink prefill when the company changes.
	dialog.fields_dict.company.df.onchange = function () {
		_apply_esalink_partner_gate();
	};

	// Inline connection test — probe the entered credentials before saving (not Esalink).
	dialog.add_custom_action(__("Test connection"), () => {
		const v = dialog.get_values(true) || {};
		if (v.platform_type === "Esalink") {
			frappe.show_alert({ message: __("Esalink connectivity is tested automatically when you register."), indicator: "blue" });
			return;
		}
		if (!v.client_id || !v.client_secret) {
			frappe.show_alert({ message: __("Enter Client ID and Client Secret first."), indicator: "orange" });
			return;
		}
		const $result = dialog.fields_dict.test_result_html.$wrapper;
		$result.html(`<div class="text-muted small">${frappe.utils.icon("loading-indicator")} ${__("Testing…")}</div>`);
		frappe.call({
			method: "etransactions.plateforme_agreee.session.test_platform_credentials",
			args: {
				platform_type: v.platform_type,
				client_id: v.client_id,
				client_secret: v.client_secret,
				api_base_url: v.api_base_url || null,
				platform_code: v.platform_code || null,
				auth_method: v.auth_method || null,
				platform_name: is_edit ? existing_name : null,
				company: v.company || null,
			},
			callback(r) {
				const res = r.message || {};
				const color = res.status === "ok" ? "green" : "red";
				$result.html(
					`<div class="indicator-pill ${color}" style="margin-top:4px">${frappe.utils.escape_html(res.message || etransactions.status_labels.health(res.status))}</div>`
				);
			},
		});
	});

	if (is_edit) {
		frappe.call({
			method: "etransactions.etransactions.doctype.etransactions_accredited_platform.etransactions_accredited_platform.get_platforms",
			callback(r) {
				if (r.message) {
					const p = r.message.find((x) => x.name === existing_name);
					if (p) {
						dialog.set_values(p);
						_toggle_redirect_url(p.platform_type);
						if (p.platform_type === "Esalink") _render_esalink_status();
					}
				}
			},
		});
	} else if (preset_type) {
		dialog.set_value("platform_type", preset_type);
		if (preset_type === "SuperPDP") dialog.set_value("platform_code", "superpdp");
		else if (preset_type === "Esalink") dialog.set_value("platform_code", "esalink");
		_toggle_redirect_url(preset_type);
		_apply_esalink_partner_gate();
	}

	dialog.show();
}

// Dedicated "Register on Esalink" flow: prefill the company data, ask clearly for the
// routing address (the company SIREN by default), then create/reuse the Esalink customer,
// mint its credentials and persist them on the given platform row.
function _open_esalink_registration_dialog(frm, { platform_name, company, transaction_type, on_done }) {
	let partner_ready = true;
	// Keep the routing address mirroring the legal identifier until the user edits it directly.
	let routing_touched = false;
	// Company identifiers loaded from the prefill, keyed by legal-id type.
	const prefill = { siren: "", siret: "" };

	const legal_id_for = (type) => (type === "SIRET" ? prefill.siret : prefill.siren) || "";

	const d = new frappe.ui.Dialog({
		title: __("Register on Esalink"),
		size: "large",
		fields: [
			{ fieldtype: "HTML", fieldname: "notice" },
			{
				fieldtype: "Data",
				fieldname: "routing_address",
				label: __("Routing address"),
				reqd: 1,
				description: __(
					"Where invoices are routed to. Defaults to the chosen legal identifier; edit only to route to a different identifier."
				),
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Select",
				fieldname: "legal_id_type",
				label: __("Legal identifier type"),
				options: "SIREN\nSIRET",
				default: "SIREN",
				reqd: 1,
				description: __("The identifier the company is registered under on Esalink."),
			},
			{ fieldtype: "Data", fieldname: "customerLegalId", label: __("Legal identifier"), reqd: 1 },
			{ fieldtype: "Section Break", label: __("Company") },
			{ fieldtype: "Data", fieldname: "customerName", label: __("Company Name"), reqd: 1 },
			{ fieldtype: "Data", fieldname: "customerVat", label: __("VAT Number") },
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Data",
				fieldname: "customerEmail",
				label: __("Contact Email"),
				reqd: 1,
				description: __("Esalink sends the KYC onboarding email here."),
			},
			{ fieldtype: "Section Break", label: __("Address") },
			{ fieldtype: "Data", fieldname: "addressLine1", label: __("Address Line 1"), reqd: 1 },
			{ fieldtype: "Data", fieldname: "addressLine2", label: __("Address Line 2") },
			{ fieldtype: "Column Break" },
			{ fieldtype: "Data", fieldname: "postalCode", label: __("Postal Code"), reqd: 1 },
			{ fieldtype: "Data", fieldname: "city", label: __("City"), reqd: 1 },
			{ fieldtype: "Data", fieldname: "country", label: __("Country (ISO 2-letter)"), reqd: 1 },
		],
		primary_action_label: __("Register"),
		primary_action(values) {
			if (!partner_ready) {
				frappe.show_alert({
					message: __("Set the Esalink partner credentials in site_config.json first."),
					indicator: "red",
				});
				return;
			}
			const customer_data = {
				customerName: values.customerName,
				customerLegalId: values.customerLegalId,
				customerVat: values.customerVat,
				customerEmail: values.customerEmail,
				addressLine1: values.addressLine1,
				addressLine2: values.addressLine2,
				postalCode: values.postalCode,
				city: values.city,
				country: values.country,
			};
			frappe.call({
				method: "etransactions.plateforme_agreee.esalink_provisioning.register_esalink_company",
				args: {
					company,
					transaction_type: transaction_type || "Both",
					customer_data: JSON.stringify(customer_data),
					routing_address: values.routing_address || null,
					platform_name: platform_name || null,
					legal_id_type: (values.legal_id_type || "SIREN").toLowerCase(),
				},
				freeze: true,
				freeze_message: __("Registering on Esalink…"),
				callback(r) {
					if (r.exc) return;
					d.hide();
					_show_esalink_result(r.message || {});
					if (on_done) on_done();
				},
			});
		},
	});

	// Mirror the routing address from the chosen legal identifier, until the user edits the
	// routing field directly. Only the identifier is shown: its scheme (SIREN → 0225,
	// SIRET → 0009) is derived server-side from the legal-identifier type.
	function sync_routing_from_legal_id() {
		if (routing_touched) return;
		d.set_value("routing_address", d.get_value("customerLegalId") || "");
	}
	d.fields_dict.routing_address.df.onchange = function () {
		routing_touched = true;
	};
	d.fields_dict.legal_id_type.df.onchange = function () {
		d.set_value("customerLegalId", legal_id_for(d.get_value("legal_id_type") || "SIREN"));
		sync_routing_from_legal_id();
	};
	d.fields_dict.customerLegalId.df.onchange = sync_routing_from_legal_id;

	// Prefill from the company + surface the partner-credentials gate and missing-data hints.
	const $notice = d.fields_dict.notice.$wrapper;
	$notice.html(`<div class="text-muted small">${frappe.utils.icon("loading-indicator")} ${__("Loading company data…")}</div>`);
	frappe
		.xcall("etransactions.plateforme_agreee.esalink_provisioning.esalink_registration_prefill", {
			company,
			platform_name: platform_name || null,
		})
		.then((cfg) => {
			prefill.siren = cfg.siren || "";
			prefill.siret = cfg.siret || "";
			["customerName", "customerVat", "customerEmail", "addressLine1", "addressLine2", "postalCode", "city"].forEach((f) => {
				d.set_value(f, cfg[f] || "");
			});
			d.set_value("country", cfg.country || "FR");
			const type = (cfg.legal_id_type || "siren").toUpperCase();
			d.set_value("legal_id_type", type);
			const legal_id = legal_id_for(type) || cfg.customerLegalId || "";
			d.set_value("customerLegalId", legal_id);
			d.set_value("routing_address", legal_id);
			// The programmatic set_value calls above may have flagged the routing field as touched;
			// reset so the legal-id → routing-address mirror keeps working for the user's own edits.
			routing_touched = false;

			partner_ready = !!cfg.partner_ready;
			let html = "";
			if (!partner_ready) {
				html += `<div class="indicator-pill red" style="margin-bottom:6px">${__(
					"Esalink partner credentials missing — set esalink_partner_username, esalink_partner_password and esalink_api_key in site_config.json."
				)}</div>`;
				d.disable_primary_action();
			} else {
				d.enable_primary_action();
			}
			const issues = cfg.issues || [];
			if (issues.length) {
				html += `<div class="text-muted small">${__("Complete the fields below (missing on the company):")}<br>${issues
					.map((i) => frappe.utils.escape_html(i))
					.join("<br>")}</div>`;
			}
			$notice.html(html);
		})
		.catch(() => $notice.empty());

	d.show();
}

// Report the outcome of an Esalink registration (state + customer id + integration test).
function _show_esalink_result(res) {
	const STATE = {
		created: __("Esalink account created"),
		reused: __("Linked to the existing Esalink account"),
		existing: __("Already linked to Esalink"),
	};
	const health =
		res.health_status === "ok"
			? __("Integration test passed.")
			: __("Integration test: {0}", [
					frappe.utils.escape_html(
						res.health_message || (res.health_status ? etransactions.status_labels.health(res.health_status) : "—")
					),
				]);
	frappe.msgprint({
		title: __("Esalink registration"),
		indicator: "green",
		message:
			`<p>${STATE[res.state] || frappe.utils.escape_html(res.state || "")}${res.customer_id ? ` · ${__("Customer: {0}", [frappe.utils.escape_html(res.customer_id)])}` : ""}.</p>` +
			`<p class="text-muted small">${__("Status: {0}", [frappe.utils.escape_html(etransactions.status_labels.esalink_customer(res.status))])} — ${health}</p>` +
			`<p class="text-muted small">${__("The account activates automatically once Esalink validates the KYC onboarding.")}</p>`,
	});
}

