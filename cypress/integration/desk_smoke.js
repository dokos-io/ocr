context("Desk smoke", () => {
	before(() => {
		cy.login();
	});

	it("boots the desk on a set-up site", () => {
		cy.visit("/desk/home");

		// A site whose setup is incomplete redirects every route to the setup wizard,
		// which would make every other spec fail in a confusing way.
		cy.location("pathname").should("not.contain", "setup-wizard");
		cy.get("body").should("have.attr", "data-ajax-state", "complete");
	});

	it("runs against the UI test company", () => {
		// Guard rail: if baseUrl points at the wrong site (an unresolved hostname falls
		// through to the bench's default site), every later spec would write into
		// somebody's real data. Fail loudly here instead.
		cy.window().its("frappe.boot.sysdefaults.company").should("eq", "UI Test Co");
	});

	it("has e-invoicing switched on", () => {
		// Every eTransactions field and panel is gated on this boot flag, so without it
		// the e-invoicing specs would fail on missing DOM rather than on real breakage.
		cy.visit("/desk/home");
		cy.window().its("frappe.boot.einvoicing_enabled").should("eq", 1);
	});

	it("lists received e-invoices", () => {
		cy.go_to_list("eInvoice");
		cy.location("pathname").should("eq", "/desk/einvoice");
		cy.get(".list-row-container, .no-result").should("exist");
	});
});
