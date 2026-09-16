// Display labels for status codes returned by the accredited platforms. The codes are
// stored and compared as-is; only their rendering goes through these maps so that the
// UI never shows a raw wire value such as "WAITING_VALIDATION" or "ok".
frappe.provide("etransactions.status_labels");

Object.assign(etransactions.status_labels, {
	// Esalink partner account status (`esalink_customer_status`).
	esalink_customer(status) {
		const map = {
			WAITING_VALIDATION: __("Waiting for validation"),
			ACTIVE: __("Active"),
			REJECTED: __("Rejected"),
			INACTIVE: __("Inactive"),
		};
		return status ? map[status] || __(status) : "—";
	},

	// Directory identifier status (`identifierStatus` on Esalink).
	directory_identifier(status) {
		const map = {
			NEW: __("New"),
			DELETE: __("Deletion requested"),
			UPDATE: __("Update requested"),
			IN_PROGRESS: __("In Progress"),
			WAITINGACTIVATE: __("Waiting for activation"),
			WAITINGPEPPOL: __("Waiting for Peppol"),
			WAITINGOPTIN: __("Waiting for opt-in"),
			REFUSED: __("Refused"),
			ERROR: __("Error"),
			DONE: __("Done"),
			Active: __("Active"),
			Inactive: __("Inactive"),
			Upcoming: __("Upcoming"),
		};
		return status ? map[status] || __(status) : "";
	},

	// Platform health check outcome (`last_health_status`).
	health(status) {
		const map = { ok: __("Connected"), error: __("Connection error") };
		return status ? map[status] || __(status) : __("Not tested");
	},
});
