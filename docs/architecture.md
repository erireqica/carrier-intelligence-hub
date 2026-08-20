# Stage 3 Architecture

```text
React + TanStack Query
        |
        | credentialed JSON API + X-CSRF-Token on mutations
        v
FastAPI routes
        |
        | authentication/RBAC dependencies
        | agency-scoped domain services
        v
SQLAlchemy 2 + Alembic
        |
        v
PostgreSQL 17
```

The browser starts with `GET /api/v1/auth/me`. A valid HttpOnly session cookie produces the current user, agency, role, and a session-bound CSRF token; otherwise protected routes redirect to login. TanStack Query owns server state and the typed API client centralizes credentials, CSRF headers, errors, and JSON parsing.

FastAPI handlers remain thin. Reusable dependencies authenticate sessions and require Manager access. Services enforce agency ownership, Agent assignments, state transitions, and audit creation. Pydantic schemas define request and response contracts. SQLAlchemy models preserve the separation among long-lived cases, individual communications, tasks, review decisions, source evidence, and audit events.

The current data path is:

```text
explicit development seed -> PostgreSQL -> scoped FastAPI endpoint -> TanStack Query -> React page
```

Gmail authorization is separate from Carrier Hub authentication. A signed-in user starts OAuth with a CSRF-protected request. The backend stores only a hash of a short-lived, one-time state bound to that user and browser session, redirects the browser to Google, verifies the callback state, exchanges the code server-side, asks Gmail for the authorized account identity, and encrypts the resulting tokens before PostgreSQL persistence.

```text
Carrier Hub session -> OAuth state -> Google consent -> backend callback
                    -> token exchange -> encrypted PostgreSQL credential
```

Mailbox work runs in a standalone process, never in FastAPI startup. This lets API availability and poll timing scale and fail independently. Each connection is isolated so one unavailable or revoked account cannot terminate the whole pass.

```text
poller -> CONNECTED/ERROR connection -> unread IDs -> idempotency check
       -> sender metadata -> agency whitelist -> full MIME message
       -> CarrierMessage RECEIVED + PENDING attachment metadata
```

Unapproved messages stop after the metadata lookup, so their body is not fetched or persisted. Approved messages enter the existing domain model as idempotent source records. Stage 3 does not create cases, tasks, evidence, reviews, classification, summary, or priority; that semantic processing remains a later responsibility. Dashboard Gmail health is derived from scoped connection status—not merely row existence.

Security boundaries are server-side. The raw session token exists only in an HttpOnly cookie, passwords use Argon2id, unsafe requests require CSRF validation, CORS allows credentials only from the configured frontend origin, and every Manager API independently checks the role. Google access and refresh tokens are encrypted with a key that lives only in the ignored backend environment. OAuth codes, state values, tokens, keys, and message bodies are excluded from application audit metadata and worker logs.
