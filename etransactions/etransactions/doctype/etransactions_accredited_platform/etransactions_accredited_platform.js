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
