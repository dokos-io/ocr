/**
 * A smoke pass over the *sales* side of e-invoicing.
 *
 * Both legs share `invoice_readiness.js` and `lifecycle.js`, and the readiness panel's
 * server endpoint is now doctype-agnostic — so a change made for purchases can break
 * sales silently. This spec is deliberately thin: it asserts the shared panels render
 * and report findings, and never sends anything to a platform.
 */
context("Outbound e-invoicing smoke", () => {
	before(() => {
		cy.login();
	});

	it("shows live readiness while a Sales Invoice is being built", () => {
		cy.new_form("Sales Invoice");
		cy.set_form_value("customer", "ui_test_customer");
		cy.add_item_row("ui_test_item", 1);
		cy.await_form_idle();

		// The panel lives in the eInvoice tab and evaluates the in-memory document, so
		// it must render before the invoice is ever saved.
		cy.readiness_panel().should("exist");
		cy.expect_no_error_dialog();
	});

	it("keeps reporting readiness once the invoice is submitted", () => {
		cy.save();
		cy.submit_doc();
		cy.await_form_idle();

		cy.readiness_panel().should("exist");
		// Nothing was sent, so there is no platform status to show — but the panel must
		// still render rather than throw, which is what the post-send branch used to do
		// on the purchase side.
		cy.readiness_panel().should("have.attr", "data-et-pa-status", "");
		cy.expect_no_error_dialog();
	});
});
