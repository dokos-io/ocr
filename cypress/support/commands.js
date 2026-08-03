// etransactions-specific Cypress commands.
//
// The generic desk vocabulary (cy.login, go_to_list, new_form, fill_field, ...) comes
// from apps/frappe/cypress/support/commands.js, and the erpnext transaction-form helpers
// (await_form_idle, set_form_value, submit_doc, create_from, desk_search) from
// apps/erpnext/cypress/support/commands.js. Both are imported by ./e2e.js — only add
// helpers here that are about e-invoicing.

/**
 * Make sure a desk page is loaded before a fixture call.
 *
 * The fixture endpoints go through cy.call(), which reads `frappe.csrf_token` off the
 * application window — and that only exists once the desk has booted. A `before()` hook
 * that has just run cy.login() is still on Cypress's blank page, so the call would fail
 * on a missing property rather than on anything real.
 */
Cypress.Commands.add("desk_ready", () => {
	return cy.window({ log: false }).then((win) => {
		if (win.frappe && win.frappe.csrf_token) {
			return;
		}
		cy.visit("/desk/home");
		cy.window({ log: false }).its("frappe.csrf_token").should("be.a", "string");
	});
});

/**
 * Receive one incoming e-invoice exactly as the hourly cron would.
 *
 * Drives the real `poll_incoming_flows()` against a stub platform client, then fetches
 * the flow content inline (the production path enqueues that, and the UI job runs no
 * background worker). Resolves to `{einvoice, supplier_invoice}`.
 */
Cypress.Commands.add("receive_einvoice", (args = {}) => {
	return cy
		.desk_ready()
		.then(() => cy.call("etransactions.tests.ui_test_fixtures.receive_incoming_flow", args))
		.then((r) => r.message);
});

/**
 * Report a lifecycle status on a received e-invoice without calling a platform, so the
 * timeline on the Purchase Invoice has something to render.
 */
Cypress.Commands.add("record_einvoice_event", (einvoice, status = "in_hand") => {
	return cy
		.desk_ready()
		.then(() =>
			cy.call("etransactions.tests.ui_test_fixtures.record_lifecycle_event", { einvoice, status })
		)
		.then((r) => r.message);
});

/**
 * Remove the documents a previous run received.
 *
 * testIsolation is off and CI retries specs, so every spec that receives an e-invoice
 * has to be safe to run twice against the same site.
 */
Cypress.Commands.add("reset_einvoicing", () => {
	return cy
		.desk_ready()
		.then(() => cy.call("etransactions.tests.ui_test_fixtures.reset_einvoicing", {}));
});

/**
 * The e-invoicing lifecycle block `lifecycle.js` adds to the form dashboard.
 *
 * Selects on the data-et-lifecycle hook rather than the section heading, which is
 * translated and would make the suite fail on a French site.
 */
Cypress.Commands.add("lifecycle_panel", () => {
	return cy.get("[data-et-lifecycle]", { timeout: 30000 });
});

/** The readiness panel `invoice_readiness.js` renders into etransactions_status_html. */
Cypress.Commands.add("readiness_panel", () => {
	return cy.get("[data-et-readiness]", { timeout: 30000 });
});

/**
 * Assert no error dialog is on screen.
 *
 * The panels are add-ons layered over an invoice the user is working in: a server error
 * in one of them shows up as a traceback dialog over the form, which is a failure even
 * though the form itself rendered.
 */
Cypress.Commands.add("expect_no_error_dialog", () => {
	cy.get(".modal-dialog .msgprint, .modal-dialog .traceback").should("not.exist");
});
