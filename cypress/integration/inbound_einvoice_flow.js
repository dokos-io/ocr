/**
 * The inbound e-invoicing chain, end to end in the desk:
 *
 *   accredited platform -> eInvoice -> prefilled Supplier Invoice -> Purchase Invoice
 *
 * with the e-invoice's status and lifecycle visible on the Purchase Invoice at the end.
 *
 * The first step cannot start in the browser: it is an hourly cron talking to an
 * accredited platform. cy.receive_einvoice() runs that cron server-side against a stub
 * client (see etransactions/tests/ui_test_fixtures.py), so everything the spec then
 * asserts on was produced by the production ingestion path.
 */
context("Inbound e-invoice flow", () => {
	// Plain closure variables rather than cy.as() aliases: Cypress clears aliases between
	// tests — including ones registered in a before() hook — so every test after the first
	// would fail on a missing alias. testIsolation is off, so what the fixture produced
	// stays on the site for the whole file.
	let received;
	let purchase_invoice;

	before(() => {
		cy.login();
		cy.reset_einvoicing();
		cy.receive_einvoice().then((result) => {
			received = result;
		});
	});

	it("records the received flow as an eInvoice", () => {
		cy.visit(`/desk/einvoice/${received.einvoice}`);
		cy.await_form_idle();

		cy.window()
			.its("cur_frm.doc")
			.then((doc) => {
				expect(doc.einvoice_type, "einvoice_type").to.eq("Incoming");
				expect(doc.seller_name, "seller_name").to.eq("LE FOURNISSEUR");
				expect(doc.id, "invoice number").to.be.a("string").and.not.be.empty;
				// The original file was downloaded and parsed, not just announced.
				expect(doc.pa_content_state, "pa_content_state").to.eq("fetched");
				expect(doc.grand_total, "grand_total").to.be.greaterThan(0);
			});

		cy.expect_no_error_dialog();
	});

	it("creates a Supplier Invoice prefilled from the e-invoice", () => {
		// Not a string: Supplier Invoice is autoincrement-named, so the fixture returns a
		// number.
		expect(received.supplier_invoice, "a Supplier Invoice must have been generated").to.not.be
			.undefined;

		cy.visit(`/desk/supplier-invoice/${received.supplier_invoice}`);
		cy.await_form_idle();

		cy.window()
			.its("cur_frm.doc")
			.then((doc) => {
				expect(doc.einvoice, "einvoice link").to.eq(received.einvoice);
				// Resolved from the seller's tax id, not left blank for the accountant.
				expect(doc.supplier, "supplier").to.eq("LE FOURNISSEUR");
				expect(doc.bill_no, "bill_no").to.be.a("string").and.not.be.empty;
				expect(doc.supplier_grand_total, "supplier_grand_total").to.be.greaterThan(0);
				expect(doc.items, "line items").to.have.length.greaterThan(0);
				// The received file is attached, so the preview has something to show.
				expect(doc.file, "attached file").to.be.a("string");
			});

		cy.expect_no_error_dialog();
	});

	it("creates the Purchase Invoice from the Supplier Invoice", () => {
		cy.visit(`/desk/supplier-invoice/${received.supplier_invoice}`);
		cy.await_form_idle();

		// The received lines carry the seller's product ids, which match no Dokos
		// Item, so a Purchase Invoice line would have no expense account to inherit.
		// Picking the item is the accountant's step in this flow.
		cy.window()
			.its("cur_frm.doc.items")
			.then((items) => {
				for (let idx = 1; idx <= items.length; idx++) {
					cy.set_child_value("items", idx, "item_code", "ui_test_item");
				}
			});
		// Only when the picks changed something: Cypress retries the test, and on the
		// second run the rows already carry the item, so the desk answers "No changes in
		// document" and never sends the request cy.save() waits for.
		cy.window().then((win) => {
			if (win.cur_frm.is_dirty()) {
				cy.save();
			}
		});

		// The save re-renders the form — the button field relabels itself on refresh — so
		// a click issued straight after it lands on an element Cypress sees detached.
		cy.window().should((win) => {
			expect(win.cur_frm.doc.__unsaved, "the form must be saved before creating the invoice").to
				.not.be.ok;
		});
		cy.await_form_idle();

		// The form's own affordance: a Button field that asks whether to submit.
		//
		// Clicked through the field rather than a selector: the desk re-renders this
		// control and leaves the previous button behind, so the selector matches two
		// elements — one of them clipped by an overflow:hidden parent — and Cypress can
		// resolve neither. The field's own button is the node its handler is bound to.
		cy.window().then((win) => {
			win.cur_frm.get_field("create_purchase_invoice").$input.trigger("click");
		});
		cy.get(".modal-dialog:visible").should("exist");
		// On a retry the draft the previous attempt created still exists, and the form
		// asks which of the two to use before it offers to create anything.
		cy.get(".modal-dialog:visible").then(($modal) => {
			if ($modal.find("button:contains('Create a new invoice')").length) {
				cy.findByRole("button", { name: "Create a new invoice" }).click();
				cy.get(".modal-dialog:visible").should("exist");
			}
		});
		cy.findByRole("button", { name: "Create and keep in draft" }).click();

		// The creation is a server round-trip announced only by a toast, whose text is
		// translated — so read the invoice back instead. cy.call() resolves once and has
		// no retry of its own, hence the poll.
		poll_for_purchase_invoice(received.supplier_invoice).then((name) => {
			purchase_invoice = name;
		});
	});

	it("shows the e-invoice status and lifecycle on the Purchase Invoice", () => {
		// Without this the visit below lands on a blank new-invoice form and every
		// assertion fails on "undefined", hiding which test actually broke.
		expect(purchase_invoice, "the previous test must have created a Purchase Invoice").to.be.a(
			"string"
		);

		// Give the timeline something to render, the way the platform would.
		cy.record_einvoice_event(received.einvoice, "in_hand");

		cy.visit(`/desk/purchase-invoice/${purchase_invoice}`);
		cy.await_form_idle();

		// --- the eInvoice reference is on the invoice itself ---
		cy.window().its("cur_frm.doc.einvoice").should("eq", received.einvoice);
		cy.window().its("cur_frm.doc.etransactions_pa_flow_id").should("not.be.empty");

		// --- the lifecycle panel renders, with the PA ribbon and the event ---
		cy.lifecycle_panel().should("have.attr", "data-et-einvoice", received.einvoice);
		cy.lifecycle_panel().find(".et-lc-ribbon").should("exist");
		cy.lifecycle_panel().find(".et-lc-events tbody tr").should("have.length.greaterThan", 0);

		// --- the readiness panel renders instead of throwing ---
		// Regression guard: this used to call a Sales-Invoice-only endpoint with
		// the Purchase Invoice's name, so the server raised DoesNotExistError and
		// put a traceback dialog over the form.
		cy.readiness_panel().should("exist");
		cy.expect_no_error_dialog();
	});

	it("links back from the eInvoice to what it produced", () => {
		cy.visit(`/desk/einvoice/${received.einvoice}`);
		cy.await_form_idle();

		cy.get(".form-dashboard-section.form-links").should("contain.text", "Supplier Invoice");
		cy.get(".form-dashboard-section.form-links").should("contain.text", "Purchase Invoice");
	});
});

/** Read back the Purchase Invoice a Supplier Invoice produced, waiting for it to exist. */
function poll_for_purchase_invoice(supplier_invoice, attempts = 20) {
	return cy
		.call("frappe.client.get_value", {
			doctype: "Purchase Invoice",
			filters: { supplier_invoice },
			fieldname: "name",
		})
		.then((r) => {
			const name = (r.message || {}).name;
			if (name) {
				return name;
			}
			if (attempts <= 1) {
				throw new Error(`no Purchase Invoice was created for ${supplier_invoice}`);
			}
			return cy
				.wait(500)
				.then(() => poll_for_purchase_invoice(supplier_invoice, attempts - 1));
		});
}
