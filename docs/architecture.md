# Foundation Architecture

The current application is a small monorepo with one browser client and one API service:

```text
React + TypeScript
        |
        | HTTP/REST
        v
FastAPI + Pydantic
        |
        | SQLAlchemy sessions
        v
PostgreSQL
```

The readiness page calls the typed `GET /api/v1/health` endpoint through TanStack Query. FastAPI validates the response with a Pydantic schema. The database module prepares a synchronous SQLAlchemy engine and request-scoped session pattern, while Alembic points at the same settings and model metadata. No domain tables exist yet, so there is intentionally no placeholder migration.

## Why this shape fits the product

- **React + TypeScript** supports a responsive, data-heavy operations interface while catching client-side contract mistakes early.
- **FastAPI** provides typed REST endpoints, validation, dependency injection, and generated API documentation with little framework ceremony.
- **PostgreSQL** is a durable relational system of record suited to cases, tasks, users, audit events, and uniqueness constraints needed for idempotent email processing.
- **A monorepo** keeps the frontend, backend, documentation, and shared development workflow together while preserving clear service boundaries.

Configuration comes from environment variables. Browser code receives only its public API base URL; database credentials remain backend-only. Future features should extend these boundaries rather than bypass them.
