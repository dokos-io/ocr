# PA Connection — Plateforme Agréée Integration

This package (`etransactions.plateforme_agreee`) connects eTransactions to a **PA
(Plateforme Agréée / Plateforme de Dématérialisation Partenaire — a certified
e-invoicing platform)**. Under the French e-invoicing & e-reporting reform, every
invoice between French businesses must transit through such a platform, which routes the
document to the buyer via the public directory (*annuaire*) and reports its lifecycle
status back to both parties.

The package abstracts three different platform backends behind **one unified client
interface**, so the rest of the app never needs to know which PA a given company uses.

---

# Part A — Overview

## What the PA connection does

| Capability | Direction | Entry point |
|------------|-----------|-------------|
| Submit an outgoing invoice | out | `eInvoice.send_to_plateform()` |
| Poll a submitted invoice's status | out | `flow.poll_pending_outgoing_flows()` (hourly) |
| Fetch incoming supplier invoices | in | `flow.poll_incoming_flows()` (hourly) |
| Report a lifecycle status (CDAR) | out | `eInvoice.submit_lifecycle_status()` / `auto_status.*` |
| Receive counterparty lifecycle events | in | `flow.poll_outgoing_lifecycle_events()` + `flow.poll_incoming_lifecycle_flows()` (hourly) |
| Sync the customer directory (*annuaire*) | — | `directory.sync_customer_directory()` (manual) / `sync_all_customers()` (daily) |

## The three supported platforms

The `platform_type` field on **eTransactions Accredited Platform** selects the backend:

| `platform_type` | Client class | Transport | Lifecycle delivery |
|-----------------|--------------|-----------|--------------------|
| `SuperPDP` | `SuperPDPClient` | SuperPDP REST API (`/v1.beta/…`) | events **inline** on the invoice |
| `Custom` | `AFNORClient` | AFNOR XP Z12-013 standard REST | separate **CDAR** flows |
| `Esalink` | `EsalinkClient` | HUBTIMIZE REST — AFNOR-shaped, `POST /v1/token` JSON auth + `hubtimize-api-key` header | separate **CDAR** flows |

The key behavioural split is the last column: **SuperPDP exposes lifecycle events inline
on each invoice**, whereas **AFNOR/Esalink deliver them as separate incoming CDAR flows**.
That is why two distinct polling jobs exist (see [Cron jobs](#cron-jobs--document-hooks)).

## Configuration

PA configuration lives in two DocTypes:

- **eTransactions Accredited Platform** — one record per company per platform. Holds the
  `platform_type`, the OAuth2 `client_id` / `client_secret` (Password fields), the
  optional `api_base_url`, the `transaction_type` it covers (`Sales` / `Purchases` /
  `Both`), `is_active`, `auto_send_on_submit`, and `directory_refresh_days` (default 15).
  `platform_code` is auto-set to `superpdp` / `esalink` in `validate()`.
  Credentials live **only on the record** — `client_id` / `client_secret` are never read
  from `site_config.json` (the doctype tests lock this in). Esalink's *environment* is picked
  per record on `esalink_environment` (`test` / `prod`, default `prod`); only the
  `esalink_api_key` and the partner credentials come from `site_config`.
- **eTransactions Settings** (singleton) — the auto-status flags `auto_send_in_hand`,
  `auto_send_approved`, `auto_send_payment`.

**Read-only directory fallback.** Sends and e-reporting always use the company's *own*
active PA (`get_client`). Read-only directory lookups (`get_directory_client`) are more
lenient: if the company has no active PA, or its PA fails to authenticate/connect (e.g.
stale credentials → `401 invalid_client`), they fall back to the first other `is_active`
platform (ordered by creation) — safe because a directory query submits no document under
any company's identity.

CRUD on platforms is exposed through whitelisted helpers in
[`../etransactions/doctype/etransactions_accredited_platform/etransactions_accredited_platform.py`](../etransactions/doctype/etransactions_accredited_platform/etransactions_accredited_platform.py):
`get_platforms`, `save_platform`, `delete_platform` (guards against deleting a default or
in-use platform), `toggle_active`.

## End-to-end flow

```
OUTGOING (sales)
  Sales Invoice submit
    └─ overrides/sales_invoice.on_submit
         └─ flow.send_einvoice_to_plateforme(einvoice)
              └─ eInvoice.send_to_plateform()
                   ├─ get_client(company, customer)         # session.py factory
                   ├─ client.submit_invoice(file, …)        # → FlowResult
                   └─ db_set(pa_flow_id, pa_status="sent")
  …hourly…
  flow.poll_pending_outgoing_flows()  → client.get_invoice_status() → pa_status
  flow.poll_outgoing_lifecycle_events()→ client.get_lifecycle_events() → eInvoice Event (SuperPDP)

INCOMING (purchases)
  …hourly…
  flow.poll_incoming_flows()
    ├─ client.list_incoming_invoices()  → IncomingFlow[]
    ├─ client.download_flow(flow_id)    → bytes
    └─ eInvoice.create_from_plateforme_flow()  → Incoming eInvoice (+ Supplier Invoice)
  flow.poll_incoming_lifecycle_flows()  → CDAR flows → pyfrctc.parse_cdar() → eInvoice Event
```

---

# Part B — Architecture reference

## Module map

### Orchestration layer — `etransactions/plateforme_agreee/`

| File | Role |
|------|------|
| [`session.py`](session.py) | Platform resolution + **client factory** (`get_platform_for_context`, `get_client`, legacy `get_session`) |
| [`flow.py`](flow.py) | Submission helper + the four polling cron jobs |
| [`auto_status.py`](auto_status.py) | Document-event handlers that auto-emit lifecycle statuses |
| [`directory.py`](directory.py) | Annuaire sync (`sync_customer_directory`, `sync_all_customers`) |
| [`routing.py`](routing.py) | Identifier parsing + routing resolution (`parse_directory_identifier`, `resolve_routing`, `address_for_siret`) |
| [`lifecycle_status.py`](lifecycle_status.py) | Canonical status registry + per-platform code mapping |
| [`cdar.py`](cdar.py) | CDAR XML data builder (`build_cdar_data`, `generate_cdar_flow`) over `pyfrctc.generate_cdar` |
| [`esalink_provisioning.py`](esalink_provisioning.py) | Esalink account registration via HUBTIMIZE's partner Customer API (`/v1/customerPA`): create a customer per company, mint its `clientId`/`clientSecret`, register the directory line |

### Platform clients — `etransactions/components/`

| File | Role |
|------|------|
| [`../components/superpdp/client.py`](../components/superpdp/client.py) | `SuperPDPClient` — OAuth2 client-credentials, token caching, raw + unified API methods |
| [`../components/superpdp/models.py`](../components/superpdp/models.py) | Platform-agnostic dataclasses (the shared vocabulary, see below) |
| [`../components/afnor/client.py`](../components/afnor/client.py) | `AFNORClient` — XP Z12-013 REST, lifecycle via CDAR flows |
| [`../components/esalink/client.py`](../components/esalink/client.py) | `EsalinkClient` (per-company operations) + `EsalinkPartnerClient` (integrator `/v1/customerPA` provisioning). Both subclass `AFNORClient` and swap in HUBTIMIZE's token auth + `hubtimize-api-key` header |
| `../components/ext/superpdp.json`, `../components/ext/ESALINK_API_*.yml` | SuperPDP / HUBTIMIZE OpenAPI specs (reference) |

## The unified client interface

`get_client()` returns one of `SuperPDPClient`, `AFNORClient`, or `EsalinkClient`. All
three implement the same method set; callers in `flow.py`, `directory.py`, `auto_status.py`
and `eInvoice` never import a concrete client.

| Method | Returns | Notes |
|--------|---------|-------|
| `submit_invoice(file_content, filename, syntax, external_id, processing_rule)` | `FlowResult` | sends an outgoing invoice |
| `get_invoice_status(flow_id)` | `StatusResult` | maps platform codes → `sent`/`pending`/`done`/`error` |
| `list_incoming_invoices()` | `list[IncomingFlow]` | new supplier invoices |
| `download_flow(flow_id)` | `bytes` | raw invoice / CDAR file |
| `get_directory_for_siren(siren)` | `DirectoryData` | annuaire lookup |
| `submit_lifecycle_status(*, flow_id, status, einvoice, details, attachments)` | `LifecycleResult` | SuperPDP → native event; AFNOR/Esalink → CDAR flow |
| `list_incoming_lifecycle_flows()` | `list[IncomingFlow]` | empty for SuperPDP; CDAR `*InvoiceLC` flows for AFNOR/Esalink |
| `get_lifecycle_events(flow_id)` | `list[LifecycleEvent]` | inline events for SuperPDP; empty for AFNOR/Esalink |

### Normalized models — `components/superpdp/models.py`

Plain `@dataclass`es that every client maps its raw API payloads into, so higher layers
stay platform-agnostic:

`FlowResult`, `StatusResult`, `IncomingFlow`, `DirectoryData` (+ `DirectoryLineData`),
`LifecycleResult` (`event_id` for native-event platforms, `flow_id` for CDAR platforms —
exactly one is set), `LifecycleEvent`.

## Platform resolution & factory — `session.py`

`get_platform_for_context(company, customer, transaction_type)` resolves the platform name
by this precedence:

1. `Customer.accredited_platform_override` (if a customer is given)
2. `Customer Group.accredited_platform_override`
3. First active **eTransactions Accredited Platform** for the company whose
   `transaction_type` matches (`Sales`/`Purchases`/`Both`), ordered by creation
4. `eTransactions Settings.default_sales_platform` / `default_purchases_platform`

`get_client(company, customer, transaction_type)` then reads the credentials via
`platform_doc.get_password(...)` and dispatches on `platform_type`:

- `SuperPDP` → `SuperPDPClient(client_id, client_secret, base_url)`
- `Custom` → `AFNORClient(client_id, client_secret, base_url)` (base URL **required**)
- otherwise (Esalink) → `EsalinkClient(username=client_id, password=client_secret,
  api_key, base_url)` — the company's minted `clientId`/`clientSecret`, with the
  `hubtimize-api-key` from `site_config` (`esalink_api_key()`) and the base URL derived from
  the record's `esalink_environment` (`base_url_for_environment()`, defaulting to `prod`)

`get_session()` is retired — Esalink no longer exposes a raw `pyfrctc` session — and now
throws; use `get_client()` for all platforms.

## Per-platform notes

### SuperPDP — `components/superpdp/client.py`
- OAuth2 client-credentials at `POST {base}/oauth2/token`; token cached and refreshed 60 s
  before expiry. Default base URL `https://api.superpdp.tech`.
- Invoices: `POST /v1.beta/invoices` (raw body, `Content-Type` derived from syntax —
  `application/pdf` for Factur-X else `application/xml`); listing auto-paginates via
  `has_after` / `starting_after_id`.
- Status is **derived from the invoice's append-only `events[]`** by weighting status
  codes (`error` > `done` > `pending` > `sent`). Code families: `api:*` (created/received/
  rejected), `ppf:003-005` (PPF transmission/acceptance/rejection), `fr:204-207` (lifecycle).
- Lifecycle is reported with `create_invoice_event()` (`POST /v1.beta/invoice_events`) and
  read inline via `get_lifecycle_events()`. Only `fr:204/205/206/207` are supported.
- Directory lookup uses `GET /v1.beta/french_directory/entries?number={siren}`.

### AFNOR (`Custom`) — `components/afnor/client.py`
- Generic client for **any** XP Z12-013-compliant PA; the base URL makes it provider-agnostic.
- OAuth2 at `POST /v1/oauth2/token` with credentials as **query parameters** (per the
  AFNOR/Esalink spec).
- Flows submitted multipart to `POST /v1/flows` (`flowInfo` JSON + `file`, includes a
  SHA-256). Status from `GET /v1/flows/{id}?docType=Metadata` → `acknowledgement.status`
  (`Pending`/`Ok`/`Error`). Search via `POST /v1/flows/search` (requires `updatedAfter`,
  defaults to last 30 days).
- Directory via `GET /v1/siren/code-insee:{siren}` + `POST /v1/directory-line/search`.
- Lifecycle is sent as a **CDAR flow** (`submit_flow(..., "CDAR")`) built by
  `cdar.generate_cdar_flow()`; incoming lifecycle arrives as `CustomerInvoiceLC` /
  `SupplierInvoiceLC` flows.

### Esalink (HUBTIMIZE) — `components/esalink/client.py` + `esalink_provisioning.py`
- **Not** `pyfrctc` — a native HTTP client. `EsalinkClient` subclasses `AFNORClient` (so it
  reuses the entire Flows/Directory/lifecycle interface and the CDAR-based lifecycle model)
  and only swaps the transport: auth via `POST /v1/token` with a JSON `{username, password}`
  body, plus a mandatory `hubtimize-api-key` header on every call. Base URL is per-environment
  (`ppd.hubtimize.fr` for `test`, `hubtimize.fr` for `prod`).
- **Account provisioning** (`esalink_provisioning.py`) is Esalink-specific: `EsalinkPartnerClient`
  (the integrator's `/v1/customerPA` API, authenticated with partner credentials from
  `site_config`) creates a customer per company — which triggers HUBTIMIZE's KYC/KYB onboarding
  email and registers the French directory line — then mints the company's `clientId`/`clientSecret`
  via `POST /v1/customerPA/{id}/user`. The credentials are stored on the platform record and a
  scheduled poll flips it active once Esalink validates. This is the platform's
  `directory_registration_via_partner` capability (see `session.PLATFORM_CAPABILITIES`).

## Document data model

| DocType | Purpose | Key PA fields |
|---------|---------|---------------|
| **eInvoice** | core invoice record | `pa_directory_line`, `pa_processing_rule` (`B2B`/`B2G`/`B2C`/`OutOfScope`), `pa_flow_id`, `pa_status` (`created`/`sent`/`pending`/`done`/`error`), `pa_submitted_at`, `pa_updated_at`, `pa_flow_type` (`CustomerInvoice`/`SupplierInvoice`/`*LC`), `pa_syntax` (`Factur-X`/`UBL`/`CII`), `pa_error_details` |
| **eInvoice Event** | one lifecycle event | `direction` (in/out), `status`, `state`, `pa_event_id`, `pa_flow_id`, `reason_code`/`reason_text`, `action_code`/`action_text`, `comment`, `amount`/`currency`/`payment_date` |
| **eInvoicing Directory Line** | annuaire routing entry per party + establishment | `customer` **xor** `supplier`, `identifier`, `siren`/`siret` (parsed from the identifier), `address` (the matching establishment Address), `line_type`, `line_status`, `routing_code`, `commitment_required` |
| **eTransactions Accredited Platform** | PA config (per company) | see [Configuration](#configuration) |
| **eTransactions Settings** | singleton defaults | default platforms + auto-status flags |
| **eInvoicing Log** | audit trail | `operation_type`, `origin`, `status`, `new_count`/`updated_count`, `logs` |

### Routing resolution

A legal entity (one SIREN) can hold many establishments (SIRET) and service codes —
i.e. many directory lines. The routing target of an invoice is an *establishment*,
which maps to an **Address** (custom fields `siret` + `etransactions_buyer_reference`).

During sync, `directory.py` parses each annuaire `identifier` (`parse_directory_identifier`)
to fill `siren`/`siret`/`routing_code`/`line_type`, then binds the line to the party's
Address whose SIRET matches (`address_for_siret`).

`routing.resolve_routing(party_type, party, address)` then picks the line for a
transaction, in order: the active line bound to the invoice's address → the customer's
`default_directory_line` → the single active line (if unambiguous) → `None` (fall back to
the manual BT-34/BT-49 electronic address). It is the single source used by
`cdar.build_cdar_data` (recipient routing, MDT-73), `generator.map_electronic_addresses`
(buyer BT-49), and `sales_invoice._create_update_einvoice` (auto-fills `pa_directory_line`).

Relevant `eInvoice` methods (in
[`../etransactions/doctype/einvoice/einvoice.py`](../etransactions/doctype/einvoice/einvoice.py)):

- `send_to_plateform()` — requires `einvoice_type == "Outgoing"` and a
  `seller_electronic_address` (BT-34); picks the file via `_get_file_for_pa()` (prefers the
  attached Factur-X PDF, else generates one), submits, and `db_set`s the `pa_*` fields. Uses
  `db_set` deliberately to avoid re-triggering `validate()` (which regenerates the XML).
- `refresh_pa_status()` — polls `get_invoice_status()` and updates `pa_status` /
  `pa_updated_at` / `pa_error_details`.
- `submit_lifecycle_status(status, comment, reason_code, …)` — validates the reason code
  when required, sends via the client, records an `eInvoice Event` and an `eInvoicing Log`.
- `create_from_plateforme_flow(flow, file_content, company)` *(classmethod)* — builds an
  Incoming eInvoice and attaches the received file; the `on_update` hook then creates the
  Supplier Invoice.

**Invariant:** once `pa_flow_id` is set the eInvoice cannot be trashed (`on_trash` guard).

## Lifecycle status system — `lifecycle_status.py`

A single **canonical status** string is the lingua franca; each client translates it to
its wire format. The `STATUSES` registry maps 10 canonical statuses to their codes:

| Canonical | MDT-105 | MDT-88 | SuperPDP | Side | Reason req. |
|-----------|---------|--------|----------|------|-------------|
| `in_hand` | 204 | 45 | `fr:204` | purchase | — |
| `approved` | 205 | 1 | `fr:205` | purchase | — |
| `partially_approved` | 206 | 49 | `fr:206` | purchase | ✓ |
| `dispute` | 207 | 46 | `fr:207` | purchase | ✓ |
| `suspended` | 208 | 39 | — | purchase | ✓ |
| `completed` | 209 | 37 | — | sale | — |
| `refused` | 210 | 50 | — | purchase | ✓ |
| `payment_sent` | 211 | 47 | — | purchase | — |
| `payment_received` | 212 | 47 | — | sale | — |
| `cancelled` | 220 | — | — | — | — |

SuperPDP only supports the four statuses that have an `fr:` code; CDAR platforms carry all
ten. Helpers: `to_superpdp_code` / `from_superpdp_code`, `to_cdar_codes` / `from_cdar_code`,
`reason_codes` / `reason_required` (MDT-113 reason lists from the CDAR schematron
`BR-FR-CDV-CL-09`), `manual_statuses(side)`, `label`, `is_warning`.

**Ordering.** There is none: the CDAR schematron validates each status message on its own,
and `INITIAL` lets any status of a side open that side's axis. In particular an invoice can
be **refused without `in_hand` having been reported first** — a buyer who spots a bad
invoice on arrival should not have to acknowledge it before rejecting it. What `TRANSITIONS`
does forbid is contradiction: nothing after `refused`/`cancelled`, no second `in_hand`, and
no refusal of an invoice already paid (`dispute` is the remedy there).

**Reason wording.** `REASON_LABELS` / `REASON_DESCRIPTIONS` give each MDT-113 code a
translatable phrase, keyed by *code* (the four lists share 27 distinct codes), and
`reason_code_options(status)` serves `{value, label, description}` to the picker.
`reason_codes()` keeps returning bare codes — it is the server-side validator. All of these
dicts use `frappe._lt`, not `_`: they are built at import time, so `_` would freeze the
wording into the first language a worker happened to serve. The accessors coerce back to
`str`, since a lazy string cannot be JSON-serialised.

## Cron jobs & document hooks

Wired in [`../hooks.py`](../hooks.py).

### Scheduled (`scheduler_events`)

| Frequency | Job | What it does |
|-----------|-----|--------------|
| hourly | `flow.poll_pending_outgoing_flows` | refresh `pa_status` for sent/pending outgoing eInvoices |
| hourly | `flow.poll_incoming_flows` | create Incoming eInvoices from new PA flows (Purchases/Both platforms) |
| hourly | `flow.poll_outgoing_lifecycle_events` | ingest counterparty events on our outgoing invoices (SuperPDP inline) |
| hourly | `flow.poll_incoming_lifecycle_flows` | download & `pyfrctc.parse_cdar()` incoming CDAR flows (AFNOR/Esalink) |
| daily | `directory.sync_all_customers` | refresh stale directory lines (older than `directory_refresh_days`) |

### Document events (`doc_events`)

Handled in [`auto_status.py`](auto_status.py); all sends are **best-effort and
non-blocking** (a platform failure is logged via `frappe.log_error`, never blocks the
accounting document):

| DocType | Event | Handler | Status sent (if flag enabled) |
|---------|-------|---------|-------------------------------|
| Supplier Invoice | `after_insert` | `on_supplier_invoice_after_insert` | `in_hand` — gated by `auto_send_in_hand` |
| Purchase Invoice | `on_submit` | `on_purchase_invoice_submit` | `approved` — gated by `auto_send_approved` |
| Payment Entry | `on_submit` | `on_payment_entry_submit` | `payment_sent` (purchase ref) / `payment_received` (sales ref) — gated by `auto_send_payment` |

Auto-status also checks `_platform_supports()`: SuperPDP silently skips statuses without an
`fr:` code, CDAR platforms accept all.

Outgoing **submission** is triggered separately from
[`../overrides/sales_invoice.py`](../overrides/sales_invoice.py) `on_submit`, which calls
`flow.send_einvoice_to_plateforme()`.

## Logging & observability — eInvoicing Log

Every PA operation writes an **eInvoicing Log** via `eInvoicingLog.create_log(result)` with
an `operation_type` (`flow_send`, `flow_status`, `flow_receive`, `lifecycle_send`,
`lifecycle_receive`, `directory_single`, `directory_all`), an `origin` (`Submit`, `Cron`,
`Manual`), counts, and a list of `(level, message)` log lines. Old logs are vacuumed daily by
`einvoicing_log.vacuum_old_logs`.

## Testing & dependencies

- [`../tests/test_lifecycle_status.py`](../tests/test_lifecycle_status.py) — pure-logic
  tests of the registry: SuperPDP and CDAR round-trips, reason codes, warnings.
- [`../tests/test_cdar.py`](../tests/test_cdar.py) — CDAR generation validated against XSD +
  Schematron for the supported statuses (outgoing/incoming, reason-code variants).
- [`../tests/test_esalink.py`](../tests/test_esalink.py) — HUBTIMIZE transport (token auth +
  `hubtimize-api-key`), the `EsalinkPartnerClient` Customer API, and the account-provisioning /
  payload-builder logic.

**`pyfrctc`** (https://pypi.org/project/pyfrctc/, declared in `pyproject.toml`)
is required only for **CDAR generation/parsing** (`generate_cdar`, `parse_cdar`) — the lifecycle
wire format shared by the AFNOR and Esalink backends. All three platform clients (SuperPDP,
AFNOR, Esalink) are native HTTP clients that need only `requests` for transport.
