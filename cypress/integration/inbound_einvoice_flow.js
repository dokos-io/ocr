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
	before(() => {
		cy.login();
		cy.reset_einvoicing();
		cy.receive_einvoice().as("received");
	});

	it("records the received flow as an eInvoice", () => {
		cy.get("@received").then(({ einvoice }) => {
			cy.visit(`/desk/einvoice/${einvoice}`);
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
	});

	it("creates a Supplier Invoice prefilled from the e-invoice", () => {
		cy.get("@received").then(({ einvoice, supplier_invoice }) => {
			expect(supplier_invoice, "a Supplier Invoice must have been generated").to.be.a("string");

			cy.visit(`/desk/supplier-invoice/${supplier_invoice}`);
			cy.await_form_idle();

			cy.window()
				.its("cur_frm.doc")
				.then((doc) => {
					expect(doc.einvoice, "einvoice link").to.eq(einvoice);
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
	});

	it("creates the Purchase Invoice from the Supplier Invoice", () => {
		cy.get("@received").then(({ supplier_invoice }) => {
			cy.visit(`/desk/supplier-invoice/${supplier_invoice}`);
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
			cy.save();

			// The form's own affordance: a Button field that asks whether to submit.
			cy.get('[data-fieldname="create_purchase_invoice"] button').click();
			cy.get(".modal-dialog:visible").should("exist");
			cy.findByRole("button", { name: "Create and keep in draft" }).click();

			// The creation is a server round-trip; read the invoice back rather than
			// racing the success dialog's render.
			cy.call("frappe.client.get_value", {
				doctype: "Purchase Invoice",
				filters: { supplier_invoice },
				fieldname: "name",
			}).then((r) => {
				const name = (r.message || {}).name;
				expect(name, "a Purchase Invoice must have been created").to.be.a("string");
				cy.wrap(name).as("purchase_invoice");
			});
		});
	});

	it("shows the e-invoice status and lifecycle on the Purchase Invoice", () => {
		cy.get("@received").then(({ einvoice }) => {
			// Give the timeline something to render, the way the platform would.
			cy.record_einvoice_event(einvoice, "in_hand");

			cy.get("@purchase_invoice").then((purchase_invoice) => {
				cy.visit(`/desk/purchase-invoice/${purchase_invoice}`);
				cy.await_form_idle();

				// --- the eInvoice reference is on the invoice itself ---
				cy.window().its("cur_frm.doc.einvoice").should("eq", einvoice);
				cy.window().its("cur_frm.doc.etransactions_pa_flow_id").should("not.be.empty");

				// --- the lifecycle panel renders, with the PA ribbon and the event ---
				cy.lifecycle_panel().should("have.attr", "data-et-einvoice", einvoice);
				cy.lifecycle_panel().find(".et-lc-ribbon").should("exist");
				cy.lifecycle_panel().find(".et-lc-events tbody tr").should("have.length.greaterThan", 0);

				// --- the readiness panel renders instead of throwing ---
				// Regression guard: this used to call a Sales-Invoice-only endpoint with
				// the Purchase Invoice's name, so the server raised DoesNotExistError and
				// put a traceback dialog over the form.
				cy.readiness_panel().should("exist");
				cy.expect_no_error_dialog();
			});
		});
	});

	it("links back from the eInvoice to what it produced", () => {
		cy.get("@received").then(({ einvoice }) => {
			cy.visit(`/desk/einvoice/${einvoice}`);
			cy.await_form_idle();

			cy.get(".form-dashboard-section.form-links").should("contain.text", "Supplier Invoice");
			cy.get(".form-dashboard-section.form-links").should("contain.text", "Purchase Invoice");
		});
	});
});
