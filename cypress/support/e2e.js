// Pull in dodock's support layer wholesale: it registers every desk command
// (cy.login, cy.go_to_list, cy.new_form, cy.fill_field, ...) plus the code-coverage
// support hooks, and swallows uncaught application exceptions. Its own imports resolve
// against apps/frappe/node_modules, so etransactions needs no Cypress dependencies.
import "../../../frappe/cypress/support/e2e";

// erpnext's desk helpers (await_form_idle, set_form_value, submit_doc, create_from,
// desk_search). etransactions is always installed alongside erpnext, and every flow
// under test runs through erpnext transactions, so these are reused rather than
// reimplemented here.
import "../../../erpnext/cypress/support/commands";

// etransactions-specific commands, layered on top.
import "./commands";
