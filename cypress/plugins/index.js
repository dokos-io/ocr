// Delegate to frappe's plugin file: it registers @cypress/code-coverage's tasks, and
// resolving it from apps/frappe means the plugin itself is looked up in
// apps/frappe/node_modules, where `bench run-ui-tests` installs it.
module.exports = require("../../../frappe/cypress/plugins/index.js");
