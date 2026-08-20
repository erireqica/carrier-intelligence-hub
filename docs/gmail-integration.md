# Gmail Integration

Carrier Hub connects a user-owned Gmail inbox through Google OAuth 2.0, ingests approved carrier mail, reads supported attachments, and projects application workflow state back to Gmail user labels. Carrier Hub login and Google authorization remain separate; the application never asks for or sees the Gmail password.

## OAuth flow

```text
Carrier Hub session
       |
       v
POST /api/v1/gmail/oauth/start
       |
       v
one-time, hashed, session-bound OAuth state
       |
       v
Google account selection and consent
       |
       v
backend callback
       |
       v
server-side code exchange + Gmail profile lookup
       |
       v
encrypted credentials in PostgreSQL
```

The callback state prevents login-CSRF and account-confusion attacks. Its raw value travels through the browser, while PostgreSQL stores only its hash. It expires after ten minutes, can be consumed once, and must match the initiating agency, user, and Carrier Hub session. The Gmail profile endpoint—not an email value supplied by the browser—identifies the authorized account.

Google issues a short-lived access token for API calls and normally an offline refresh token that can obtain future access tokens. Both are encrypted before persistence using Fernet authenticated encryption. The dedicated encryption key stays in the ignored `backend/.env`; separating the key from the database reduces the value of a database-only disclosure. Reauthorization preserves the existing refresh token when Google legitimately omits a replacement.

New and upgraded connections request only `https://www.googleapis.com/auth/gmail.modify`. Gmail requires it to modify labels on threads. Existing `gmail.readonly` credentials remain ingestion-capable, but the API and UI truthfully report that workflow labels need a permission upgrade and the label outbox waits in `NEEDS_PERMISSION`. Successful reconnection verifies the scopes actually granted, not merely requested, and resets that connection's label work to pending.

Upgrade authorization uses Google's incremental-consent option. Google may return the previously granted `gmail.readonly` scope alongside `gmail.modify`; that valid superset is accepted only when the parsed token proves `gmail.modify` is present. OAuthlib's global relaxed-scope mode is not enabled. A newly returned refresh token replaces the prior encrypted value; when Google omits one during reconnection, Carrier Hub preserves the existing encrypted refresh token while storing the actual scopes from the new access grant. The first real label call remains the capability proof.

`gmail.modify` is broader than Carrier Hub's feature. The application boundary deliberately exposes only message/metadata/attachment reads, label list/create, thread-label inspection, and `threads.modify` for the eight app-managed user labels. It has no methods for sending, drafting, deleting, trashing, untrashing, archiving, forwarding, or changing read/unread/system-label state. The reconciler computes additions and removals exclusively from stored managed-label bindings; unrelated user and system labels are untouched.

## Connection lifecycle

- `CONNECTED`: authorization is usable and the latest sync completed or the connection is ready.
- `ERROR`: a transient or unexpected safe sync failure occurred; a later successful sync recovers it.
- `NEEDS_REAUTH`: Google rejected the stored authorization, so the mailbox owner must reconnect.
- `DISCONNECTED`: local credentials were deleted; remote revocation is attempted best-effort.

Agents see and own their connections. Managers may view and manually sync agency connections, but only the mailbox owner may reconnect or disconnect one.

## Sync and ingestion

```text
poller
  |
  v
CONNECTED or retryable ERROR connection
  |
  v
unread inbox Gmail IDs within the lookback window
  |
  v
(connection ID, Gmail message ID) idempotency check
  |
  v
From/Subject metadata fetch
  |
  v
agency carrier whitelist match
  |
  v
full MIME message fetch for approved senders only
  |
  v
CarrierMessage RECEIVED + Attachment PENDING metadata
```

Polling is deliberately simple for local Stage 3 operation and avoids the Cloud Pub/Sub infrastructure and subscription lifecycle required by Gmail push notifications. The worker is a separate process from FastAPI so a slow or failing mailbox cannot affect web-server startup or request availability. Run it continuously with `python -m app.workers.gmail_poll`, once with `--once`, or target one connection with `--once --connection-id ID`. Manual UI sync calls the same synchronization service.

The query examines unread inbox messages within the configured initial lookback. Each Gmail ID is checked before any fetch. Sender metadata is then parsed and matched against the agency database. Exact enabled sender addresses win; otherwise the sender domain may exactly equal an enabled carrier domain or be its subdomain. Boundary matching means `mail.americo.com` matches `americo.com`, while `evilamerico.com` does not. This From-header whitelist is an operational allowlist, not cryptographic sender authentication such as SPF, DKIM, or DMARC verification.

Unapproved messages are counted and discarded without fetching or storing their bodies. For approved messages, the parser walks MIME parts, prefers plain text, converts HTML to readable text as a fallback, decodes URL-safe base64, and tolerates malformed or missing optional fields. Attachment filename, MIME type, size, and stable Gmail attachment identity are stored at ingestion. The processor calls the Gmail attachment read endpoint only for approved messages, decodes bytes in memory, extracts PDF text, and discards the bytes. A separate reconciler later changes only Carrier Hub workflow labels; it never changes read state or other mailbox data.

The persisted `CarrierMessage` has `processing_status=RECEIVED`. Its `case_id`, `classification`, `summary`, and `priority` remain null because source ingestion is not semantic analysis. It does not become a Case in Stage 3. Database uniqueness on `(gmail_connection_id, gmail_message_id)` plus conflict handling prevents duplicate records even if polling repeats or races. Attachment uniqueness provides the corresponding per-message protection.

## Development and production boundaries

The local Google OAuth app uses testing status and explicit test users. Google's current testing-token policies may cause refresh authorization to expire, which appears as `NEEDS_REAUTH`. Do not bypass that policy; reconnect through the UI.

Stage 3 does not claim Google production verification, a security assessment, HIPAA compliance, SOC 2 compliance, or production authorization approval. Gmail read access is a restricted Google scope. A production deployment must review and satisfy Google's then-current OAuth verification, user-data handling, and security requirements.

Current limitations include polling rather than Gmail push notifications, no OCR, and no cryptographic authentication of the From header. Label state is a recoverable projection of PostgreSQL, described in [pipeline reliability](pipeline-reliability.md). AI processing is documented in [AI processing](ai-processing.md).
