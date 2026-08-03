const fs = require("fs");
const path = require("path");

// Cypress and its plugins live in apps/frappe/node_modules: `bench run-ui-tests`
// installs them there and runs frappe's cypress binary with this app as the project
// root. Node resolves bare requires from this file's own directory upwards, which never
// reaches apps/frappe, so the few requires made by the config itself are resolved
// explicitly. Everything imported from within apps/frappe/cypress/** (the support
// layer) resolves normally, relative to that file's location.
const frappe_modules = path.resolve(__dirname, "..", "frappe", "node_modules");

function require_from_frappe(name, { optional = false } = {}) {
	try {
		return require(path.join(frappe_modules, name));
	} catch (e) {
		if (optional) {
			return null;
		}
		throw new Error(
			`Cannot load "${name}" from ${frappe_modules}. ` +
				"Run the suite through `bench --site <site> run-ui-tests etransactions`, " +
				"which installs Cypress and its plugins into apps/frappe.\n" +
				e.message
		);
	}
}

const { defineConfig } = require_from_frappe("cypress");
const cypressSplit = require_from_frappe("cypress-split", { optional: true });

module.exports = defineConfig({
	adminPassword: "admin",
	testUser: "frappe@example.com",
	defaultCommandTimeout: 20000,
	pageLoadTimeout: 15000,
	video: true,
	videosFolder: path.resolve(__dirname, "..", "..") + "/cypressVideos/",
	viewportHeight: 960,
	viewportWidth: 1400,
	retries: {
		runMode: 1,
		openMode: 0,
	},
	e2e: {
		setupNodeEvents(on, config) {
			on("before:browser:launch", (browser, launchOptions) => {
				if (browser.family === "chromium") {
					launchOptions.args.push("--disable-dev-shm-usage");
					launchOptions.args.push("--disable-gpu");
					launchOptions.args.push("--no-sandbox");
				}
				return launchOptions;
			});

			// Splitting tests only works when Cypress Cloud is not orchestrating parallel runs.
			if (cypressSplit && process.env.CYPRESS_CLOUD_PARALLEL !== "1") {
				cypressSplit(on, config);
			}

			// Delete videos for specs without failing or retried tests
			on("after:spec", (spec, results) => {
				if (results && results.video) {
					const failures = results.tests.some((test) =>
						test.attempts.some((attempt) => attempt.state === "failed")
					);
					if (!failures) {
						fs.unlinkSync(results.video);
					}
				}
			});

			return require("./cypress/plugins/index.js")(on, config);
		},
		testIsolation: false,
		baseUrl: "http://test_site:8000",
		specPattern: ["./cypress/integration/*.js"],
	},
});
