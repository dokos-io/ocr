import frappe
from frappe import _

from etransactions.components.common import to_db_datetime
from etransactions.plateforme_agreee.session import (
	get_client,
	get_platform_for_context,
	is_receiving_enabled,
)
from etransactions.plateforme_agreee import lifecycle_status
from etransactions.etransactions.doctype.einvoicing_log.einvoicing_log import eInvoicingLog
from etransactions.etransactions.doctype.einvoice_log.einvoice_log import log_fetch
from etransactions.etransactions.doctype.einvoice_event.einvoice_event import record_event


#: How many stuck flows one hourly sweep re-attempts inline. Each makes one or two HTTP
#: calls to the platform, so the sweep stays bounded; the rest are picked up next hour.
MAX_INLINE_CONTENT_RETRIES = 20

#: A flow still "pending" after this many attempts has hit something the fetch cannot
#: report on its own. Escalated to "error" so it stops looking like a transient state.
STALLED_CONTENT_ATTEMPTS = 3

#: How often to repeat the "receiving is switched off but this site used to receive"
#: warning. The condition persists until someone acts on it, so it is stated once a day
#: rather than on all 24 polls.
RECEIVING_DISABLED_LOG_INTERVAL_HOURS = 24


def send_einvoice_to_plateforme(einvoice_name: str):
	"""Send an outgoing eInvoice to the accredited platform.

	Enqueued after commit from sales_invoice.on_submit() (auto-send). System-
	initiated, so it bypasses the interactive permission gate on send_to_plateform.
	"""
	einvoice = frappe.get_doc("eInvoice", einvoice_name)
	einvoice.flags.ignore_permissions = True

	result = {
		"operation_type": "flow_send",
		"origin": "Submit",
		"company": einvoice.company,
		"new_count": 0,
		"updated_count": 0,
		"logs": [],
	}

	try:
		einvoice.send_to_plateform()
		result["new_count"] = 1
		result["logs"].append(("info", f"eInvoice {einvoice_name} submitted. Flow ID: {einvoice.pa_flow_id}"))
	except Exception as e:
		result["logs"].append(("error", f"Failed to submit eInvoice {einvoice_name}: {str(e)}"))
		eInvoicingLog.create_log(result)
		raise

	eInvoicingLog.create_log(result)


def poll_pending_outgoing_flows():
	"""Cron: poll the PA for status updates on all pending/sent outgoing eInvoices."""
	pending = frappe.get_all(
		"eInvoice",
		filters={
			"einvoice_type": "Outgoing",
			"pa_flow_id": ["is", "set"],
			"pa_status": ["in", ["sent", "pending"]],
		},
		fields=["name", "company", "sales_invoice"],
	)

	clients: dict = {}
	for row in pending:
		company = row.company
		if company not in clients:
			try:
				clients[company] = get_client(company)
			except Exception:
				clients[company] = None

		client = clients.get(company)
		if not client:
			continue

		result = {
			"operation_type": "flow_status",
			"origin": "Cron",
			"company": company,
			"new_count": 0,
			"updated_count": 0,
			"logs": [],
		}

		try:
			einvoice = frappe.get_doc("eInvoice", row.name)
			einvoice.refresh_pa_status()
			result["updated_count"] = 1
			result["logs"].append(("info", f"eInvoice {row.name} status updated to {einvoice.pa_status}"))
		except Exception as e:
			result["logs"].append(("warning", f"Failed to refresh status for eInvoice {row.name}: {str(e)}"))

		eInvoicingLog.create_log(result)


def poll_outgoing_lifecycle_events():
	"""Cron: pull counterparty lifecycle events for our outgoing eInvoices.

	Works for platforms that expose events inline on the invoice (SuperPDP);
	CDAR-based platforms (Esalink/AFNOR) return nothing here and are handled by
	``poll_incoming_lifecycle_flows()``.
	"""
	cutoff = frappe.utils.add_days(frappe.utils.nowdate(), -90)
	outgoing = frappe.get_all(
		"eInvoice",
		filters={
			"einvoice_type": "Outgoing",
			"pa_flow_id": ["is", "set"],
			"pa_submitted_at": [">=", cutoff],
		},
		fields=["name", "company", "pa_flow_id"],
	)

	clients: dict = {}
	for row in outgoing:
		company = row.company
		if company not in clients:
			try:
				clients[company] = get_client(company)
			except Exception:
				clients[company] = None
		client = clients.get(company)
		if not client:
			continue

		result = {
			"operation_type": "lifecycle_receive",
			"origin": "Cron",
			"company": company,
			"new_count": 0,
			"updated_count": 0,
			"logs": [],
		}
		try:
			for event in client.get_lifecycle_events(row.pa_flow_id):
				created = record_event(
					row.name,
					direction="in",
					status=event.status,
					state="done",
					status_datetime=event.datetime,
					pa_event_id=event.pa_event_id,
					pa_flow_id=row.pa_flow_id,
					reason_code=event.reason_code,
					reason_text=event.reason_text,
					action_code=event.action_code,
					action_text=event.action_text,
					comment=event.comment,
				)
				if created:
					result["new_count"] += 1
					result["logs"].append(
						("info", f"Recorded incoming status '{event.status}' for eInvoice {row.name}")
					)
		except Exception as e:
			result["logs"].append(("warning", f"Could not read lifecycle events for eInvoice {row.name}: {str(e)}"))

		if result["new_count"] or result["logs"]:
			eInvoicingLog.create_log(result)


def poll_incoming_lifecycle_flows():
	"""Cron: fetch incoming CDAR lifecycle flows (Esalink/AFNOR) and record events."""
	try:
		from pyfrctc import parse_cdar
	except ImportError:
		parse_cdar = None

	active_platforms = frappe.get_all(
		"eTransactions Accredited Platform",
		filters={"is_active": 1},
		fields=["company"],
		group_by="company",
	)

	for company_row in active_platforms:
		company = company_row.company
		result = {
			"operation_type": "lifecycle_receive",
			"origin": "Cron",
			"company": company,
			"new_count": 0,
			"updated_count": 0,
			"logs": [],
		}

		try:
			client = get_client(company)
			lc_flows = client.list_incoming_lifecycle_flows()
		except Exception as e:
			result["logs"].append(("error", f"Failed to list lifecycle flows: {str(e)}"))
			eInvoicingLog.create_log(result)
			continue

		if lc_flows and parse_cdar is None:
			result["logs"].append(("error", "pyfrctc is required to parse incoming CDAR flows."))
			eInvoicingLog.create_log(result)
			continue

		for flow in lc_flows:
			if not flow.flow_id:
				continue
			if frappe.db.exists("eInvoice Event", {"pa_event_id": flow.flow_id}):
				continue
			try:
				content = client.download_flow(flow.flow_id)
				parsed = parse_cdar(content)
			except Exception as e:
				result["logs"].append(("warning", f"Could not parse CDAR flow {flow.flow_id}: {str(e)}"))
				continue

			canonical = lifecycle_status.from_cdar_code(parsed.get("status_code"))
			if not canonical:
				continue

			# The event may arrive before the invoice it refers to. Record it
			# unlinked rather than dropping it: eInvoice.after_insert claims it by
			# pa_flow_id, and the flow is not downloaded and parsed again on every
			# run in the meantime.
			einvoice = frappe.db.get_value(
				"eInvoice", {"id": parsed.get("invoice_number"), "company": company}, "name"
			)
			if not einvoice:
				result["logs"].append(
					("info", f"CDAR flow {flow.flow_id} recorded ahead of invoice {parsed.get('invoice_number')}")
				)

			detail = (parsed.get("doc_status") or [{}])[0]
			created = record_event(
				einvoice,
				direction="in",
				status=canonical,
				state="done",
				status_datetime=parsed.get("lc_datetime"),
				pa_event_id=flow.flow_id,
				pa_flow_id=flow.flow_id,
				reason_code=detail.get("reason_code"),
				reason_text=detail.get("reason_txt"),
				action_code=detail.get("action_code"),
				action_text=detail.get("action_txt"),
				comment=detail.get("comment"),
			)
			if created:
				result["new_count"] += 1
				result["logs"].append(
					("info", f"Recorded incoming status '{canonical}' for eInvoice {einvoice or '(pending)'}")
				)

		if result["new_count"] or result["logs"]:
			eInvoicingLog.create_log(result)


def submit_pending_ereporting_entries():
	"""Cron: batch pending B2C e-reporting entries and submit them to the platform.

	Entries are grouped by company and kind; the platform aggregates them and
	declares them to the PPF on its own schedule. Only platforms advertising the
	``ereporting`` capability are processed.
	"""
	from etransactions.plateforme_agreee.ereporting import ereporting_platform

	companies = frappe.get_all(
		"eReporting Entry",
		filters={"state": "pending"},
		fields=["company"],
		group_by="company",
		pluck="company",
	)

	for company in companies:
		if not ereporting_platform(company, "sales"):
			continue

		result = {
			"operation_type": "ereporting_send",
			"origin": "Cron",
			"company": company,
			"new_count": 0,
			"updated_count": 0,
			"logs": [],
		}
		try:
			client = get_client(company, transaction_type="sales")
		except Exception as e:
			result["logs"].append(("error", str(e)))
			eInvoicingLog.create_log(result)
			continue

		for kind in ("transaction", "payment"):
			names = frappe.get_all(
				"eReporting Entry",
				filters={"company": company, "kind": kind, "state": "pending"},
				pluck="name",
			)
			if not names:
				continue
			_submit_ereporting_batch(client, kind, names, result)

		if result["new_count"] or result["logs"]:
			eInvoicingLog.create_log(result)


def _submit_ereporting_batch(client, kind: str, names: list[str], result: dict):
	"""Submit one company's batch of entries of a single kind, recording outcomes."""
	docs = [frappe.get_doc("eReporting Entry", n) for n in names]
	try:
		if kind == "transaction":
			created = client.create_b2c_transactions([d.to_b2c_transaction() for d in docs])
		else:
			created = client.create_b2c_payments([d.to_b2c_payment() for d in docs])
	except Exception as e:
		for d in docs:
			d.db_set("state", "error", update_modified=False)
			d.db_set("error_details", str(e)[:500], update_modified=False)
		result["logs"].append(("error", f"Failed to submit {len(docs)} {kind} entries: {str(e)}"))
		return

	# The platform returns one result per submitted entry, matched by position —
	# the only correlation available (no client reference is echoed). If the
	# counts disagree we cannot map ids reliably, so flag for manual review rather
	# than risk a wrong pa_entry_id or a duplicate re-declaration on the next run.
	if len(created) != len(docs):
		for d in docs:
			d.db_set("state", "error", update_modified=False)
			d.db_set(
				"error_details",
				f"Platform returned {len(created)} results for {len(docs)} submitted "
				f"{kind} entries; references cannot be mapped. Manual review required.",
				update_modified=False,
			)
		result["logs"].append((
			"error",
			f"{kind}: platform returned {len(created)} results for {len(docs)} entries; "
			"marked for manual review to avoid mismatched/duplicate declarations.",
		))
		return

	for d, item in zip(docs, created):
		pa_id = item.get("id") if isinstance(item, dict) else None
		d.db_set("pa_entry_id", str(pa_id) if pa_id is not None else None, update_modified=False)
		d.db_set("state", "sent", update_modified=False)
		result["new_count"] += 1
	result["logs"].append(("info", f"Submitted {len(docs)} {kind} entries"))


def poll_ereporting_status():
	"""Cron: refresh PPF e-reporting declarations for every e-reporting platform."""
	from etransactions.plateforme_agreee.ereporting import ereporting_platform
	from etransactions.etransactions.doctype.ereporting_declaration.ereporting_declaration import (
		eReportingDeclaration,
	)
	from etransactions.plateforme_agreee import ereporting_status

	companies = frappe.get_all(
		"eTransactions Accredited Platform",
		filters={"is_active": 1},
		fields=["company"],
		group_by="company",
		pluck="company",
	)

	for company in companies:
		if not ereporting_platform(company, "sales"):
			continue

		result = {
			"operation_type": "ereporting_status",
			"origin": "Cron",
			"company": company,
			"new_count": 0,
			"updated_count": 0,
			"logs": [],
		}
		try:
			client = get_client(company, transaction_type="sales")
			declarations = client.list_ereportings()
		except Exception as e:
			result["logs"].append(("error", f"Failed to list e-reportings: {str(e)}"))
			eInvoicingLog.create_log(result)
			continue

		for decl in declarations:
			try:
				doc = eReportingDeclaration.upsert_from_platform(company, decl)
			except Exception as e:
				result["logs"].append(("warning", f"Could not record e-reporting {decl.id}: {str(e)}"))
				continue
			result["updated_count"] += 1
			warn = any(ereporting_status.is_warning(ev.status_code) for ev in decl.events)
			if warn:
				result["logs"].append(
					("warning", f"e-reporting {doc.name} for {doc.period_start}–{doc.period_end} was rejected/errored by the PPF")
				)

		if result["updated_count"] or result["logs"]:
			eInvoicingLog.create_log(result)


def _receiving_disabled_reason() -> str:
	"""Which of the three switches is holding the poll back."""
	if frappe.conf.get("etransactions_disable_receiving"):
		return _("the etransactions_disable_receiving site config key is set")

	settings = frappe.get_cached_doc("eTransactions Settings")
	if not settings.enable_einvoicing:
		return _("E-Invoicing is disabled in eTransactions Settings")

	return _("Receive E-Invoices is disabled in eTransactions Settings")


def _warn_receiving_disabled() -> None:
	"""Say why a site that used to receive invoices is no longer receiving any.

	Returning silently is right when e-invoicing is not in use, and staying quiet for a
	platform record merely left active is the point of the gate. But a platform that has
	completed a poll — `last_incoming_poll` is only written after a successful listing —
	was genuinely receiving, so the switch going off is a regression someone needs to see.
	Without this the outage is invisible: a disabled poll writes no log at all and its
	Scheduled Job Log still reads "Complete".
	"""
	previously_receiving = frappe.get_all(
		"eTransactions Accredited Platform",
		filters={
			"is_active": 1,
			"transaction_type": ["in", ["Purchases", "Both"]],
			"last_incoming_poll": ["is", "set"],
		},
		fields=["company"],
		group_by="company",
	)
	if not previously_receiving:
		return

	reason = _receiving_disabled_reason()
	since = frappe.utils.add_to_date(
		frappe.utils.now_datetime(), hours=-RECEIVING_DISABLED_LOG_INTERVAL_HOURS
	)

	for company_row in previously_receiving:
		already_warned = frappe.db.exists(
			"eInvoicing Log",
			{
				"operation_type": "receiving_disabled",
				"company": company_row.company,
				"creation": [">", since],
			},
		)
		if already_warned:
			continue

		eInvoicingLog.create_log(
			{
				"operation_type": "receiving_disabled",
				"origin": "Cron",
				"company": company_row.company,
				"new_count": 0,
				"updated_count": 0,
				"logs": [
					(
						"warning",
						_("Incoming invoices were not polled: {0}.").format(reason),
					)
				],
			}
		)


def poll_incoming_flows():
	"""Cron: fetch new incoming flows from the PA and create eInvoice records for each."""
	if not is_receiving_enabled():
		_warn_receiving_disabled()
		return

	active_platforms = frappe.get_all(
		"eTransactions Accredited Platform",
		filters={"is_active": 1, "transaction_type": ["in", ["Purchases", "Both"]]},
		fields=["company"],
		group_by="company",
	)

	for company_row in active_platforms:
		company = company_row.company

		result = {
			"operation_type": "flow_receive",
			"origin": "Cron",
			"company": company,
			"new_count": 0,
			"updated_count": 0,
			"logs": [],
		}

		try:
			client = get_client(company, transaction_type="purchases")
		except Exception as e:
			result["logs"].append(("error", str(e)))
			eInvoicingLog.create_log(result)
			continue

		# Poll window: resume 1h before the last successful poll (fallback: the
		# clients' own default window) so hourly runs stop re-listing the full
		# history. The known_flow_ids dedup below stays the correctness backstop.
		platform_name = get_platform_for_context(company, transaction_type="purchases")
		last_poll = (
			frappe.db.get_value("eTransactions Accredited Platform", platform_name, "last_incoming_poll")
			if platform_name
			else None
		)
		updated_after = (
			frappe.utils.add_to_date(frappe.utils.get_datetime(last_poll), hours=-1) if last_poll else None
		)
		poll_started_at = frappe.utils.now_datetime()

		try:
			incoming_flows = client.list_incoming_invoices(updated_after=updated_after)
		except Exception as e:
			result["logs"].append(("error", f"Failed to list incoming invoices: {str(e)}"))
			eInvoicingLog.create_log(result)
			log_fetch(
				operation="list_incoming_invoices",
				status="error",
				company=company,
				platform=platform_name,
				request=f"updated_after={updated_after}",
				response=str(e),
			)
			continue

		log_fetch(
			operation="list_incoming_invoices",
			status="success",
			company=company,
			platform=platform_name,
			request=f"updated_after={updated_after}",
			response=f"{len(incoming_flows)} flow(s) listed",
		)

		known_flow_ids = set(
			frappe.get_all(
				"eInvoice",
				filters={"company": company, "einvoice_type": "Incoming", "pa_flow_id": ["is", "set"]},
				pluck="pa_flow_id",
			)
		)

		failed_flow_times = []

		for flow_idx, flow in enumerate(incoming_flows):
			if not flow.flow_id or flow.flow_id in known_flow_ids:
				continue

			# A savepoint, not a full rollback: one flow's failure must undo only its
			# own half-written attempt, not every flow already ingested earlier in this
			# same run (bare rollback() unwinds the whole transaction back to the last
			# commit — in production that's the previous flow's own commit, but nothing
			# stops a batch of several failures in a row from reaching further back).
			# Named by index, not flow_id: a savepoint name is a bare SQL identifier and
			# a platform's flow id is free-form (dashes and all).
			save_point = f"einvoice_flow_{flow_idx}"
			frappe.db.savepoint(save_point)
			try:
				einvoice = _ingest_incoming_flow(flow, company, platform=platform_name)
				result["new_count"] += 1
				known_flow_ids.add(flow.flow_id)
				result["logs"].append(("info", f"Created eInvoice {einvoice} from incoming flow {flow.flow_id}"))
			except Exception as e:
				frappe.db.rollback(save_point=save_point)
				result["logs"].append(("error", f"Failed to create eInvoice from flow {flow.flow_id}: {str(e)}"))
				flow_time = flow.updated_at or flow.submitted_at
				if flow_time:
					failed_flow_times.append(frappe.utils.get_datetime(flow_time))

		if platform_name:
			# A flow whose ingestion failed has no eInvoice, so known_flow_ids never
			# catches it — normally harmless, since it stays inside the poll window and
			# gets retried next run. But the window itself is anchored on this very
			# timestamp: advancing it unconditionally would walk past the failed flow
			# before it ever succeeds, silently losing it for good the moment it falls
			# outside the "last poll − 1h" range. Pinning the anchor to the oldest
			# failure instead keeps it inside every window until ingestion succeeds.
			next_poll_anchor = min([poll_started_at, *failed_flow_times]) if failed_flow_times else poll_started_at
			frappe.db.set_value(
				"eTransactions Accredited Platform",
				platform_name,
				"last_incoming_poll",
				next_poll_anchor,
				update_modified=False,
			)

		eInvoicingLog.create_log(result)


def _ingest_incoming_flow(flow, company: str, platform: str | None = None) -> str:
	"""Record one incoming flow, then fetch its content out of band.

	Downloading and parsing the invoice used to happen inline, so a file the parser
	choked on left no trace at all: the flow was simply re-listed and re-downloaded
	on every hourly run. Persisting the flow first makes the inbox the durable
	record — the download and the parse can then fail, be seen, and be retried.

	Platforms that inline the invoice with the listing (SuperPDP, via ``expand[]``)
	give the record its number, dates and counterparty right away; the others show
	the flow metadata until the file arrives.

	``platform`` is the ``eTransactions Accredited Platform`` this flow was polled
	from, snapshotted onto the eInvoice so it stays correct even if the company's
	active platform changes later.
	"""
	from etransactions.etransactions.doctype.einvoice.einvoice import eInvoice

	einvoice = eInvoice.create_from_plateforme_flow(flow, None, company, platform=platform)
	_record_flow_events(einvoice, flow)
	# The worker reads its own connection, so the record has to be committed before the
	# job can pick it up. Committing here would end the transaction and destroy the
	# caller's per-flow savepoint, so the enqueue rides on the poll's own commit
	# instead: a crash mid-batch loses the batch rather than half-ingesting it, and the
	# poller re-lists those flows next hour (known_flow_ids and the pinned poll anchor
	# make that safe).
	_enqueue_content_fetch(einvoice.name)
	return einvoice.name


def _record_flow_events(einvoice, flow) -> None:
	"""Store the lifecycle events the platform returned with the flow, if any."""
	for event in getattr(flow, "events", None) or []:
		canonical = lifecycle_status.from_superpdp_code(event.get("status_code", ""))
		if not canonical:
			continue
		details = event.get("details") or []
		record_event(
			einvoice.name,
			direction="in",
			status=canonical,
			state="done",
			status_datetime=to_db_datetime(event.get("created_at")),
			pa_event_id=str(event["id"]) if event.get("id") is not None else None,
			pa_flow_id=flow.flow_id,
			comment=details[0].get("reason") if details else None,
		)


def _enqueue_content_fetch(einvoice: str) -> None:
	frappe.enqueue(
		"etransactions.plateforme_agreee.flow.fetch_einvoice_content",
		queue="long",
		job_id=f"einvoice-content::{einvoice}",
		deduplicate=True,
		enqueue_after_commit=True,
		einvoice=einvoice,
	)


def fetch_einvoice_content(einvoice: str) -> None:
	"""Background job: download and parse the original file of an incoming flow."""
	# Rolling back to a per-flow savepoint does not cancel an enqueue already registered
	# for the commit that follows, so the job can be handed a flow that was undone.
	if not frappe.db.exists("eInvoice", einvoice):
		return
	doc = frappe.get_doc("eInvoice", einvoice)
	doc.flags.ignore_permissions = True
	doc.fetch_content_from_platform()


def retry_pending_einvoice_content():
	"""Cron: re-attempt the flows whose content could not be fetched or parsed.

	Without this, a platform outage during ``poll_incoming_flows`` would leave the
	invoice stuck as metadata for good: its flow id is already known, so the poller
	skips it on every later run.

	Runs the fetch inline rather than only re-enqueueing it. Enqueueing alone reports
	"dispatched N" and calls it a success even when every one of those jobs then fails
	invisibly — which is how an incoming invoice came to sit at "pending" for days with
	nothing in the log to say why. Inline, the outcome lands in this sweep's own
	eInvoicing Log.
	"""
	stuck = frappe.get_all(
		"eInvoice",
		filters={
			"einvoice_type": "Incoming",
			"pa_content_state": ["in", ["pending", "error"]],
			"pa_flow_id": ["is", "set"],
		},
		fields=["name", "company", "pa_flow_id", "pa_content_attempts", "pa_content_state"],
		order_by="creation asc",
	)
	if not stuck:
		return

	# One log per company: eInvoicing Log is read (and filtered) per company, so a
	# run spanning several must not collapse into a single company-less row.
	results: dict[str, dict] = {}

	def result_for(company: str) -> dict:
		return results.setdefault(
			company,
			{
				"operation_type": "flow_receive",
				"origin": "Cron",
				"company": company,
				"new_count": 0,
				"updated_count": 0,
				"logs": [],
			},
		)

	for idx, row in enumerate(stuck[:MAX_INLINE_CONTENT_RETRIES]):
		result = result_for(row.company)
		if _escalate_stalled_content(row, result):
			continue

		# One invoice's failure must not undo the ones already retried in this same run.
		save_point = f"einvoice_retry_{idx}"
		frappe.db.savepoint(save_point)
		try:
			doc = frappe.get_doc("eInvoice", row.name)
			doc.flags.ignore_permissions = True
			doc.fetch_content_from_platform()
		except Exception as e:
			frappe.db.rollback(save_point=save_point)
			result["logs"].append(("error", f"Content retry failed for eInvoice {row.name}: {str(e)}"))
		else:
			frappe.db.release_savepoint(save_point)
			if frappe.db.get_value("eInvoice", row.name, "pa_content_state") == "fetched":
				result["updated_count"] += 1

	for row in stuck[MAX_INLINE_CONTENT_RETRIES:]:
		_enqueue_content_fetch(row.name)

	for result in results.values():
		if result["logs"] or result["updated_count"]:
			eInvoicingLog.create_log(result)


def _escalate_stalled_content(row, result: dict) -> bool:
	"""Mark a flow that keeps being retried without ever reporting why, and say so.

	``fetch_content_from_platform`` records its own failures as ``pa_content_state =
	"error"``. A record that is still ``pending`` after several attempts is therefore
	one whose fetch died before it could report anything — a bug, not a platform
	outage — and left alone it would retry silently forever. Returns whether the flow
	was escalated (and so should be skipped this run).
	"""
	if row.pa_content_state != "pending" or (row.pa_content_attempts or 0) < STALLED_CONTENT_ATTEMPTS:
		return False

	message = _(
		"The original file could not be retrieved after {0} attempts, and the failure was not"
		" reported. Check the Error Log for flow {1}."
	).format(row.pa_content_attempts, row.pa_flow_id)
	frappe.db.set_value(
		"eInvoice",
		row.name,
		{"pa_content_state": "error", "pa_content_error": message},
		update_modified=False,
	)
	result["logs"].append(
		("error", f"eInvoice {row.name} stalled at 'pending' after {row.pa_content_attempts} attempts")
	)
	return True


def _enqueue_missing_pdf_retry(einvoice: str) -> None:
	frappe.enqueue(
		"etransactions.plateforme_agreee.flow.retry_missing_pdf_attachment",
		queue="long",
		job_id=f"einvoice-pdf-retry::{einvoice}",
		deduplicate=True,
		einvoice=einvoice,
	)


def retry_missing_pdf_attachment(einvoice: str) -> None:
	"""Background job: retry attaching a readable PDF to a Supplier Invoice that has none."""
	doc = frappe.get_doc("eInvoice", einvoice)
	doc.flags.ignore_permissions = True
	doc.retry_missing_pdf_attachment()


def retry_missing_pdf_attachments():
	"""Cron: re-attempt attaching a readable PDF to Supplier Invoices that only have the
	raw XML/CII (or nothing at all).

	Bounded to 5 attempts per eInvoice (``attachment_retry_count``) — unlike
	``retry_pending_einvoice_content``, a missing PDF is cosmetic, not something to chase
	forever.
	"""
	missing = frappe.get_all(
		"Supplier Invoice",
		filters={"einvoice": ("is", "set")},
		or_filters=[["file", "in", ("", None)], ["file_url", "not like", "%.pdf"]],
		pluck="einvoice",
	)
	for einvoice_name in missing:
		if (frappe.db.get_value("eInvoice", einvoice_name, "attachment_retry_count") or 0) >= 5:
			continue
		_enqueue_missing_pdf_retry(einvoice_name)
