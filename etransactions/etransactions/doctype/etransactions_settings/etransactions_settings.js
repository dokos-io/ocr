// Copyright (c) 2026, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("eTransactions Settings", {
	refresh(frm) {
		_render_platform_management(frm);
	},
});

function _render_platform_management(frm) {
	const $wrapper = frm.fields_dict.platform_html.$wrapper;
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

	$wrapper.on("click", "#btn-add-superpdp", () => _open_platform_dialog(frm, null, "SuperPDP"));
	$wrapper.on("click", "#btn-add-esalink", () => _open_platform_dialog(frm, null, "Esalink"));
	$wrapper.on("click", "#btn-add-custom", () => _open_platform_dialog(frm, null, "Custom"));

	$wrapper.on("click", ".btn-edit-platform", function () {
		_open_platform_dialog(frm, $(this).data("name"));
	});

	$wrapper.on("click", ".btn-toggle-platform", function () {
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

	$wrapper.on("click", ".btn-delete-platform", function () {
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

	let rows = "";
	platforms.forEach((p) => {
		const active_badge = p.is_active
			? `<span class="indicator-pill green">${__("Active")}</span>`
			: `<span class="indicator-pill gray">${__("Inactive")}</span>`;
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
				<td>
					<div class="et-btn-group">
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
			{ fieldtype: "Section Break", label: __("Credentials") },
			{
				fieldtype: "Password",
				fieldname: "client_id",
				label: __("Client ID"),
			},
			{
				fieldtype: "Password",
				fieldname: "client_secret",
				label: __("Client Secret"),
			},
			{ fieldtype: "Section Break", label: __("Options"), collapsible: 1 },
			{
				fieldtype: "Check",
				fieldname: "auto_send_on_submit",
				label: __("Send to Platform on Sales Invoice Submit"),
				default: 0,
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
		],
		primary_action_label: is_edit ? __("Update") : __("Create"),
		primary_action(values) {
			// Force the right platform_code for pre-defined types
			if (values.platform_type === "SuperPDP") values.platform_code = "superpdp";
			else if (values.platform_type === "Esalink") values.platform_code = "esalink";

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
		}
	};

	if (is_edit) {
		frappe.call({
			method: "etransactions.etransactions.doctype.etransactions_accredited_platform.etransactions_accredited_platform.get_platforms",
			callback(r) {
				if (r.message) {
					const p = r.message.find((x) => x.name === existing_name);
					if (p) dialog.set_values(p);
				}
			},
		});
	} else if (preset_type) {
		dialog.set_value("platform_type", preset_type);
		if (preset_type === "SuperPDP") dialog.set_value("platform_code", "superpdp");
		else if (preset_type === "Esalink") dialog.set_value("platform_code", "esalink");
	}

	dialog.show();
}
