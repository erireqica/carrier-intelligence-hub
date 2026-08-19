# Stage 2 Architecture

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

Future Gmail ingestion should enter at the left side of the same domain model: a connection supplies idempotent carrier messages, processing associates them with carriers/cases, and extracted tasks/evidence/review items become visible through the existing API. OAuth secrets and live processing are deliberately absent in Stage 2.

Security boundaries are server-side. The raw session token exists only in an HttpOnly cookie, passwords use Argon2id, unsafe requests require CSRF validation, CORS allows credentials only from the configured frontend origin, and every Manager API independently checks the role. `backend/.env` contains local secrets and is ignored by Git.
