// Copyright (c) 2024, Dokos SAS and contributors
// For license information, please see license.txt

frappe.ui.form.on("OCR Reconciliation Dashboard", {
	refresh(frm) {
		frm.disable_save();
		frm.fields_dict["filters_section"].collapse(false);

		frm.$action_area = frm.get_field("ocr_action_area").$wrapper;
		frm.events.setup_empty_state(frm);

		frm.events.build_action_area(frm);
	},

	setup_empty_state: function(frm) {
		frm.$action_area.empty();
		frm.$action_area.append(`
			<div class="ocr-dashboard-empty-state">
				<p>
					${__("Please select a company first.")}
				</p>
			</div>
		`);
	},

	build_action_area: function(frm) {
		if (!frm.doc.company) return;

		frappe.require("ocr_dashboard.bundle.js", () =>
			frm.dashboard_manager = new ocr.ocr_dashboard.DashboardManager({
				doc: frm.doc,
				$wrapper: frm.$action_area,
			})
		);
	},

	company: function (frm) {
		if (frm.doc.company) {
			frm.events.build_action_area(frm);
		} else {
			frm.events.setup_empty_state(frm);
		}
	},
});
