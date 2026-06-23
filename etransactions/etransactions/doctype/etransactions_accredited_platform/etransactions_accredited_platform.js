frappe.ui.form.on("eTransactions Accredited Platform", {
	refresh(frm) {
		frm.trigger("toggle_redirect_url");
		frm.trigger("show_health");

		frm.dashboard.set_headline(
			__("Platforms are best managed from {0}.", [
				`<a href="/app/etransactions-settings">${__("eTransactions Settings")}</a>`,
			])
		);

		if (!frm.is_new()) {
			frm.add_custom_button(__("Test connection"), () => {
				frappe.call({
					method: "etransactions.plateforme_agreee.session.run_platform_health_check",
					args: { platform_name: frm.doc.name },
					freeze: true,
					freeze_message: __("Testing connection…"),
					callback(r) {
						const res = r.message || {};
						frappe.show_alert({
							message: res.message || res.status,
							indicator: res.status === "ok" ? "green" : "red",
						});
						frm.reload_doc();
					},
				});
			});

			if (frm.doc.platform_type === "SuperPDP") {
				frm.add_custom_button(__("Directory registration"), () => open_directory_dialog(frm));
			}

			if (frm.doc.platform_type === "SuperPDP" && frm.doc.is_sandbox) {
				frm.add_custom_button(__("Run sandbox test"), () => {
					frappe.call({
						method: "etransactions.plateforme_agreee.sandbox.send_superpdp_test_invoice",
						args: { platform_name: frm.doc.name },
						freeze: true,
						freeze_message: __("Provisioning test customer and sending test invoice…"),
						callback(r) {
							const res = r.message || {};
							if (!res.flow_id) return;
							frappe.msgprint({
								title: __("Sandbox test sent"),
								indicator: "green",
								message: __("Test invoice {0} sent to SuperPDP (flow {1}, status {2}).", [
									`<a href="/app/sales-invoice/${res.sales_invoice}">${res.sales_invoice}</a>`,
									res.flow_id,
									res.pa_status || "—",
								]),
							});
						},
					});
				});
			}
		}
	},

	platform_type(frm) {
		frm.trigger("toggle_redirect_url");
	},

	show_health(frm) {
		const status = frm.doc.last_health_status || "unknown";
		const map = {
			ok: ["green", __("Connected")],
			error: ["red", __("Connection error")],
			unknown: ["gray", __("Not tested")],
		};
		const [color, label] = map[status] || map.unknown;
		const when = frm.doc.last_health_check
			? ` · ${frappe.datetime.str_to_user(frm.doc.last_health_check)}`
			: "";
		frm.page.set_indicator(`${label}${when}`, color);
	},

	toggle_redirect_url(frm) {
		const is_superpdp = frm.doc.platform_type === "SuperPDP";
		frm.set_df_property("redirect_url_html", "hidden", !is_superpdp);

		if (!is_superpdp) return;

		const redirect_url = `${window.location.origin}/api/method/etransactions.plateforme_agreee.session.oauth_callback`;
		const html = `
			<div class="form-group">
				<label class="control-label">${__("Redirect URL")}</label>
				<p class="text-muted small">${__("Copy this URL into the SuperPDP application registration form.")}</p>
				<div class="input-group">
					<input type="text" class="form-control" readonly value="${redirect_url}" id="superpdp-redirect-url">
					<span class="input-group-btn">
						<button class="btn btn-default" onclick="
							navigator.clipboard.writeText('${redirect_url}');
							frappe.show_alert({message: __('Copied!'), indicator: 'green'});
						">${__("Copy")}</button>
					</span>
				</div>
			</div>`;

		frm.get_field("redirect_url_html").$wrapper.html(html);
	},
});

// --- Directory registration (own company entries, SuperPDP only) -------------

function open_directory_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Directory registration"),
		size: "large",
		fields: [
			{ fieldtype: "HTML", fieldname: "entries_html" },
			{ fieldtype: "Section Break", label: __("Add an entry") },
			{
				fieldtype: "Select",
				fieldname: "directory",
				label: __("Directory"),
				options: [
					{ value: "ppf", label: __("FR (PPF)") },
					{ value: "peppol", label: __("Peppol") },
				],
				default: "ppf",
				reqd: 1,
			},
			{ fieldtype: "Column Break" },
			{
				fieldtype: "Data",
				fieldname: "identifier",
				label: __("Identifier"),
				description: __("Peppol address, e.g. 0225:123456789"),
				reqd: 1,
			},
		],
		primary_action_label: __("Add entry"),
		primary_action(values) {
			frappe.call({
				method: "etransactions.plateforme_agreee.own_directory.register_directory_entry",
				args: { platform_name: frm.doc.name, identifier: values.identifier, directory: values.directory },
				freeze: true,
				freeze_message: __("Registering…"),
				callback() {
					frappe.show_alert({ message: __("Entry registered."), indicator: "green" });
					d.set_value("identifier", "");
					load_directory_entries(frm, d);
				},
			});
		},
	});

	// Suggest the company's SIREN as a Peppol address (0225 = French SIRENE scheme).
	if (frm.doc.company) {
		frappe.db.get_value("Company", frm.doc.company, "siren_number").then((r) => {
			const siren = r.message && r.message.siren_number;
			if (siren && !d.get_value("identifier")) d.set_value("identifier", `0225:${siren}`);
		});
	}

	d.show();
	load_directory_entries(frm, d);
}

function load_directory_entries(frm, d) {
	const $wrap = d.fields_dict.entries_html.$wrapper;
	$wrap.html(`<div class="text-muted">${frappe.utils.icon("loading-indicator")} ${__("Loading entries…")}</div>`);
	frappe.call({
		method: "etransactions.plateforme_agreee.own_directory.list_directory_entries",
		args: { platform_name: frm.doc.name },
		callback(r) {
			render_directory_entries($wrap, r.message || [], frm, d);
		},
	});
}

function render_directory_entries($wrap, entries, frm, d) {
	if (!entries.length) {
		$wrap.html(`<div class="text-muted">${__("No directory entries yet.")}</div>`);
		return;
	}
	const rows = entries
		.map((e) => {
			const dir = e.directory === "peppol" ? __("Peppol") : __("FR (PPF)");
			return `<tr>
				<td>${frappe.utils.escape_html(e.identifier || "")}</td>
				<td>${dir}</td>
				<td>${frappe.utils.escape_html(e.status || "")}</td>
				<td class="text-right"><button class="btn btn-xs btn-danger et-dir-remove" data-id="${e.id}">${__("Remove")}</button></td>
			</tr>`;
		})
		.join("");
	$wrap.html(`
		<table class="table table-bordered" style="margin-bottom:0">
			<thead><tr>
				<th>${__("Identifier")}</th><th>${__("Directory")}</th><th>${__("Status")}</th><th></th>
			</tr></thead>
			<tbody>${rows}</tbody>
		</table>`);
	$wrap.find(".et-dir-remove").on("click", function () {
		const id = $(this).attr("data-id");
		frappe.confirm(__("Remove this directory entry?"), () => {
			frappe.call({
				method: "etransactions.plateforme_agreee.own_directory.remove_directory_entry",
				args: { platform_name: frm.doc.name, entry_id: id },
				freeze: true,
				freeze_message: __("Removing…"),
				callback() {
					frappe.show_alert({ message: __("Entry removed."), indicator: "green" });
					load_directory_entries(frm, d);
				},
			});
		});
	});
}
