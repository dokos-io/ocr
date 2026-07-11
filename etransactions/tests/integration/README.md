# PA integration tests (Microcks-backed)

End-to-end tests that drive **real HTTP** from the three Plateforme Agréée (PA)
connection modes to a [Microcks](https://microcks.io) mock server, covering the
full e-invoicing and e-reporting use cases plus French annuaire registration.

Unlike the unit tests (which patch `client._request`), these exercise the whole
stack — `get_client` → the concrete client → `requests` → HTTP → response mapping
→ persisted state — so they catch auth-flow, header, URL-assembly, serialization
and status-mapping regressions that mocks at the method boundary cannot.

## How it works

- The PA clients build every URL as `base_url + path`. A single seam,
  `plateforme_agreee/_microcks.py::microcks_base_url`, redirects that base to the
  Microcks mock **only when `microcks_url` is set in site_config** — wired into
  `session._build_client` (SuperPDP / Custom / Esalink) and
  `esalink_provisioning.esalink_partner_config` (Esalink Customer API). Inert in
  production.
- Microcks serves each PA "service" at `{microcks_url}/rest/{Title}/{Version}` and
  dispatches on the OpenAPI operation path. The mock specs live in
  [`etransactions/components/mocks`](../../components/mocks) — one per service; the
  `info.title`/`info.version` must match `_MICROCKS_SERVICES` in `_microcks.py`.
- The suite **skips cleanly** when `microcks_url` is unset or Microcks is
  unreachable (`base.MicrocksTestCase.setUpClass`), so it never blocks a run
  without Microcks.

### Run it locally

```bash
./scripts/microcks-up.sh                                  # start + seed the 4 mocks
bench --site <site> set-config microcks_url http://localhost:8585
bench --site <site> run-tests --app etransactions \
    --module etransactions.tests.integration.test_einvoicing_e2e
# …repeat for test_ereporting_e2e and test_annuaire_esalink_e2e
bench --site <site> set-config microcks_url ""            # prove the skip contract
```

CI brings Microcks up as a service and sets `microcks_url` automatically (see
`.gitlab-ci.yml`).

## Coverage matrix

| Scenario | Custom (AFNOR) | SuperPDP | Esalink | Test |
|---|:-:|:-:|:-:|---|
| B2B send (Factur-X) → flow id + `sent` | ✅ | ✅ | ✅ | `test_einvoicing_e2e::test_b2b_send_roundtrips_flow_id` |
| B2G classification + send | ✅ | ✅ | ✅ | `…::test_b2g_classification_and_send` |
| UBL/Peppol send (raw XML) | ✅ | ✅ | ✅ | `…::test_ubl_peppol_send_raw_xml` |
| Status poll → `done` | ✅ | ✅ | ✅ | `…::test_status_refresh_marks_done` |
| Status poll → rejected/error + reason | ✅ | ✅ | ✅ | `…::test_status_refresh_marks_rejected` |
| Directory lookup by SIREN | ✅ | ✅ | ✅ | `…::test_directory_lookup_over_http` |
| Incoming flow list + download | ✅ | — | ✅ | `…::test_incoming_flow_roundtrip` |
| Auth handshake (healthcheck) | ✅ | ✅ | ✅ | `…::test_healthcheck_authenticates` |
| B2C capture → `eReporting Entry` | — | ✅ | — | `test_ereporting_e2e::test_b2c_sale_is_captured` |
| Batch submit → `sent` + `pa_entry_id` | — | ✅ | — | `…::test_submit_pending_entries_marks_sent` |
| Count-mismatch → `error` | — | ✅ | — | `…::test_count_mismatch_marks_error` |
| Declaration status poll | — | ✅ | — | `…::test_poll_status_upserts_declaration` |
| B2C send hard-block | — | ✅ | — | `…::test_b2c_send_is_blocked` |
| Annuaire: provision account | — | — | ✅ | `test_annuaire_esalink_e2e::test_register_company_provisions_account` |
| Annuaire: status poll activates | — | — | ✅ | `…::test_status_poll_activates_platform` |
| Annuaire: identifier register/list/remove | — | — | ✅ | `…::test_directory_identifier_register_list_remove` |
| Annuaire: resend KYC email | — | — | ✅ | `…::test_resend_kyc_email` |
| Annuaire: partner-creds gate | — | — | ✅ | `…::test_registration_blocked_without_partner_credentials` |

E-reporting is SuperPDP-only (capability `ereporting`); AFNOR/Esalink stub those
endpoints. Incoming lifecycle CDAR flows are exercised at the list/download HTTP
level only — parsing a full CDAR payload is covered by `tests/test_cdar.py`.

## Tested flows

### E-invoice send

```mermaid
sequenceDiagram
    participant T as Test
    participant EI as eInvoice.send_to_plateform
    participant S as session.get_client
    participant C as PA client
    participant M as Microcks
    T->>EI: send_to_plateform()
    EI->>S: get_client(company, customer)
    S-->>EI: client (base_url → Microcks)
    EI->>C: submit_invoice(bytes, filename, syntax)
    C->>M: POST /oauth2|/v1/oauth2|/v1 token
    M-->>C: access_token
    C->>M: POST /v1.beta/invoices | /v1/flows
    M-->>C: {flow id}
    C-->>EI: FlowResult(flow_id)
    EI->>EI: db_set(pa_flow_id, pa_status="sent")
```

### Status / lifecycle poll

```mermaid
sequenceDiagram
    participant F as flow.poll_pending_outgoing_flows
    participant EI as eInvoice.refresh_pa_status
    participant C as PA client
    participant M as Microcks
    F->>EI: refresh_pa_status()
    EI->>C: get_invoice_status(flow_id)
    C->>M: GET /v1.beta/invoices/{id} | /v1/flows/{id}?docType=Metadata
    M-->>C: events / acknowledgement
    C-->>EI: StatusResult(status, error_details)
    EI->>EI: db_set(pa_status=done|rejected|error)
```

### B2C e-reporting

```mermaid
sequenceDiagram
    participant SI as Sales Invoice.on_submit
    participant CAP as ereporting.capture_sale_transaction
    participant F as flow.submit_pending_ereporting_entries
    participant C as SuperPDPClient
    participant M as Microcks
    SI->>CAP: classify B2C/B2Bi
    CAP->>CAP: create eReporting Entry (pending)
    F->>C: create_b2c_transactions([...])
    C->>M: POST /v1.beta/b2c_transactions
    M-->>C: {data:[{id}]}
    C-->>F: created rows (matched by position)
    F->>F: entry → sent + pa_entry_id (mismatch → error)
    Note over F,M: poll_ereporting_status → GET /v1.beta/ereportings → eReporting Declaration
```

### Incoming flow

```mermaid
sequenceDiagram
    participant F as flow.poll_incoming_flows
    participant C as PA client
    participant M as Microcks
    F->>C: list_incoming_invoices(updated_after)
    C->>M: POST /v1/flows/search | GET /v1.beta/invoices?direction=in
    M-->>C: [IncomingFlow]
    F->>C: download_flow(flow_id)
    C->>M: GET /v1/flows/{id}?docType=Original | /v1.beta/invoices/{id}/download
    M-->>C: file bytes
    Note over F: eInvoice.create_from_plateforme_flow → Supplier Invoice
```

### Esalink annuaire registration

```mermaid
sequenceDiagram
    participant R as register_esalink_company
    participant P as EsalinkPartnerClient
    participant M as Microcks (Esalink Customer API)
    R->>P: find_customer_by_legal_id(siren)
    P->>M: POST /v1/customerPA/search
    M-->>P: {customers: []}  (none → create)
    R->>P: create_customer(payload)
    P->>M: POST /v1/customerPA
    M-->>P: {customerId: 777}
    R->>P: create_user(777)
    P->>M: POST /v1/customerPA/777/user
    M-->>P: {clientId, clientSecret}
    R->>R: write platform row (WAITING_VALIDATION, is_active=0)
    Note over R,M: refresh_customer_status → GET /v1/customerPA/777 (ACTIVE) → is_active=1
```

## Per-mode mock map

| Mode | `platform_type` | Client | Mock spec | Microcks service | Auth |
|---|---|---|---|---|---|
| Generic AFNOR | `Custom` | `AFNORClient` | `afnor-mock.yaml` | `AFNOR+PA+API/1.0.0` | `POST /v1/oauth2/token` (query) |
| SuperPDP | `SuperPDP` | `SuperPDPClient` | `superpdp-mock.yaml` | `SuperPDP+PA+API/1.0.0` | `POST /oauth2/token` (OAuth2) |
| Esalink (invoices) | `Esalink` | `EsalinkClient` | `esalink-mock.yaml` | `Esalink+PA+API/1.0.0` | `POST /v1/token` + `hubtimize-api-key` |
| Esalink (annuaire) | — | `EsalinkPartnerClient` | `esalink-customer-mock.yaml` | `Esalink+Customer+API/1.0.0` | `POST /v1/token` + `hubtimize-api-key` |

**Scenario selectors** — the mock returns a specific response by request value, so an
assertion traces back to a named example:

- Flow status: invoice/flow id `…-FLOW-OK`/`90001` → accepted, `…-FLOW-REJECTED`/`90002`
  → rejected/error (carries a reason), `…-FLOW-PENDING`/`90003` → pending.
- E-reporting: `POST /v1.beta/b2c_transactions` returns one row, so submitting **one**
  entry matches (→ `sent`) and **two** mismatch (→ `error`).
- Annuaire: `POST /v1/customerPA` mints customer `777`; `GET /v1/customerPA/777`
  reports `activationStatus: ACTIVE` so the status poll flips the platform active.

> Microcks does not reliably dispatch on a colon-embedded path segment
> (`/v1/siren/code-insee:{siren}`) or on POST request bodies, so those operations
> return a single deterministic example rather than varying by request.
