# Gmail Integration

Stage 3 connects a user-owned Gmail inbox through Google OAuth 2.0 and ingests approved carrier mail as source records. Stage 4 uses the same read-only authorization to fetch approved PDF attachment bytes during processing. Carrier Hub login and Google authorization remain separate; the application never asks for or sees the Gmail password.

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

Only `https://www.googleapis.com/auth/gmail.readonly` is requested. It permits reading Gmail messages and metadata but not changing labels, marking mail read, sending mail, or deleting mail. A future labels feature would require explicit new `gmail.modify` consent; Stage 3 intentionally does not request it.

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

Unapproved messages are counted and discarded without fetching or storing their bodies. For approved messages, the parser walks MIME parts, prefers plain text, converts HTML to readable text as a fallback, decodes URL-safe base64, and tolerates malformed or missing optional fields. Attachment filename, MIME type, size, and stable Gmail attachment identity are stored at ingestion. The later Stage 4 processor calls the Gmail attachment read endpoint only for approved messages, decodes bytes in memory, extracts PDF text, and discards the bytes. It never changes labels, read state, or mailbox data.

The persisted `CarrierMessage` has `processing_status=RECEIVED`. Its `case_id`, `classification`, `summary`, and `priority` remain null because source ingestion is not semantic analysis. It does not become a Case in Stage 3. Database uniqueness on `(gmail_connection_id, gmail_message_id)` plus conflict handling prevents duplicate records even if polling repeats or races. Attachment uniqueness provides the corresponding per-message protection.

## Development and production boundaries

The local Google OAuth app uses testing status and explicit test users. Google's current testing-token policies may cause refresh authorization to expire, which appears as `NEEDS_REAUTH`. Do not bypass that policy; reconnect through the UI.

Stage 3 does not claim Google production verification, a security assessment, HIPAA compliance, SOC 2 compliance, or production authorization approval. Gmail read access is a restricted Google scope. A production deployment must review and satisfy Google's then-current OAuth verification, user-data handling, and security requirements.

Current limitations include no Gmail labels or mailbox mutation, no push notifications, no OCR, and no cryptographic authentication of the From header. Stage 4 processing is documented in [AI processing](ai-processing.md).
