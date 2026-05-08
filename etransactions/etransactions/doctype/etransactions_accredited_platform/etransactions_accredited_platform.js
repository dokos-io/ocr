frappe.ui.form.on("eTransactions Accredited Platform", {
	refresh(frm) {
		frm.trigger("toggle_redirect_url");
	},

	platform_type(frm) {
		frm.trigger("toggle_redirect_url");
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
