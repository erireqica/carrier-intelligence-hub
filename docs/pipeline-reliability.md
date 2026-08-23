# Pipeline Reliability

The processing runtime uses three reusable workers and one thin scheduler:

```text
gmail_poll -> message_process -> gmail_labels
       \_______ app.workers.pipeline _______/
```

`gmail_poll` discovers unread messages, performs the sender allowlist check before a full-body fetch, and creates each approved `CarrierMessage` once. `message_process` claims eligible records, extracts supported PDFs, requests one structured AI proposal, validates it, and commits Case/Task/Evidence or Review state. `gmail_labels` independently reconciles the committed PostgreSQL state onto the Gmail thread. `pipeline` schedules these units at separate configured cadences and never runs inside FastAPI.

## Gmail labels are a projection

Each thread receives at most one workflow label:

- `AI: Processing`
- `AI: Needs Review`
- `AI: Action Required`
- `AI: No Further Action Needed`
- `AI: Failed`

Workflow precedence is `Failed > Needs Review > Action Required > Processing > No Further Action Needed`.

It may also receive at most one classification label:

- `AI: Policy Issued`
- `AI: Pending Requirements`
- `AI: Lapse Notice`
- `AI: Commission Update`

No thread has more than two Carrier Hub-managed labels. `Processed` is retired and is considered only for legacy-label removal, never as desired current state.

PostgreSQL is authoritative. For all approved messages sharing a Gmail connection and thread ID, the reconciler calculates desired labels every time. An unfinished newer message removes stale terminal/classification labels. An active Review selects Needs Review; an open/in-progress source-linked Task selects Action Required; an exhausted/permanent processing failure selects Failed. Manual Tasks do not alter source-message Gmail workflow state. At most one classification label comes from the most recent successfully finalized message when the latest thread state makes it meaningful.

Mailbox-specific label bindings store Gmail's opaque IDs. The worker lists exact user-label names, reuses existing labels, creates missing labels, tolerates a concurrent create by relisting, and repairs a binding after a user deletes a managed label. It computes `addLabelIds` and `removeLabelIds` only from those bindings, leaving system labels and unrelated user labels untouched.

## Outbox, generations, and transaction boundaries

Every Gmail-backed thread has one `GmailThreadLabelSync` outbox row. Message ingestion, finalization/failure, review Apply/Dismiss, and source-task status changes dirty the row and increment its generation in the same database transaction as the business change. The worker claims a generation with `FOR UPDATE SKIP LOCKED`, commits, calls Gmail without a database lock, and then records the result.

If state changes while Gmail is in flight, the old provider success cannot mark the newer generation applied. The row remains pending and the next pass recomputes current truth. A Gmail failure therefore cannot roll back a Case, Task, Evidence, Review, or message result. Label retries use only the label outbox and never call OpenAI.

## Retry and recovery

Message retries cover only allowlisted transient codes such as rate limits, timeouts, temporary AI service failures, and attachment download failures. Defaults are three total automatic attempts (including the initial attempt), 30-second exponential backoff, and a 600-second cap. `NEEDS_REVIEW`, semantic validation flags, permanent authentication/configuration errors, and OCR needs do not retry automatically. Exhausted rows remain `FAILED` with no next retry until an authorized manual retry.

Label delivery defaults to four total attempts, with retry delays of 30, 60, and 120 seconds after the first three failures (the exponential calculation is capped at 600 seconds). Missing `gmail.modify` becomes `NEEDS_PERMISSION`; invalid authorization marks the connection for reconnection; missing threads and permanent malformed requests require attention. Transient network/rate-limit/5xx failures become `RETRY_WAIT`. Authorized recovery endpoints can reset delivery state without changing AI/business results, but desired labels and normal retries remain worker-driven rather than user-selected.

A crash can leave a claim in `PROCESSING`. Each worker first recovers claims older than its configured lease (600 seconds for messages, 300 for labels), records a safe audit event, and makes the work eligible again. Claims and provider work use separate transactions and per-item sessions, so one mailbox, message, or thread failure does not monopolize the cycle.

## Operational visibility and cost protection

The Gmail Connections UI shows modify capability, label backlog/attention, message retry timing, and per-thread label status. Manager dashboard metrics distinguish processing retry/exhaustion from Gmail-label pending/attention. Audit events contain internal IDs, counts, attempts, logical labels, and safe error codes—not subjects, bodies, client/policy data, provider payloads, or credentials.

Idempotent Gmail message identity, the durable `gmail_observed_messages` ledger, one analysis and one Review lifecycle per message, stable Case identity, source-linked Task uniqueness, evidence replacement, and one thread outbox row prevent duplicate operational work. The ledger is keyed by logical Gmail connection and immutable message ID, survives CarrierMessage deletion/reset, and remains valid across reconnect and verified same-mailbox handoff. A successful message is never returned to AI because Gmail label delivery failed. The deliberate default model is `gpt-5.6-terra`; automated tests use fakes and consume no provider credits.
