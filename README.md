# Carrier Intelligence Hub

Carrier Intelligence Hub is an authenticated internal operations application for insurance agencies. It turns carrier communications into durable policy cases, assigned work, review items, evidence, and audit history. Stage 2 provides a real PostgreSQL-backed Agent and Manager workflow; Gmail OAuth, live ingestion, and AI extraction remain future work.

## Stack

- React, TypeScript, Vite, React Router, TanStack Query, and Tailwind CSS
- FastAPI, Pydantic, SQLAlchemy 2, Alembic, and psycopg 3
- PostgreSQL 17
- Argon2id password hashing and database-backed browser sessions
- Vitest/Testing Library, pytest, ESLint/Prettier, and Ruff

## Local setup

PostgreSQL 17 should be running on port `5433`. The setup script securely prompts for the PostgreSQL administrator password and a demo-login password. It creates only the dedicated `carrier_hub_app` role and the `carrier_intelligence_hub` and `carrier_intelligence_hub_test` databases, then writes an ignored `backend/.env`.

```powershell
cd backend
pwsh -ExecutionPolicy Bypass -File .\scripts\setup_postgres.ps1
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& .\.venv\Scripts\python.exe -m alembic upgrade head
& .\.venv\Scripts\python.exe -m app.db.seed
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The seed command is explicit, development-only, and idempotent. It requires `DEMO_SEED_PASSWORD` in `backend/.env`, never prints that password, and creates these synthetic accounts:

- `manager@demo.local` — Manager
- `agent.one@demo.local` — Agent
- `agent.two@demo.local` — Agent

All three use the locally supplied demo password. No Gmail connection or OAuth credential is seeded.

In a second terminal:

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

Open `http://localhost:5173`. The API is at `http://localhost:8000`, with OpenAPI documentation at `http://localhost:8000/docs`.

## Verification

```powershell
cd backend
& .\.venv\Scripts\python.exe -m ruff check .
& .\.venv\Scripts\python.exe -m ruff format --check .
& .\.venv\Scripts\python.exe -m pytest
& .\.venv\Scripts\python.exe -m alembic current

cd ..\frontend
npm run lint
npm run format:check
npm run test -- --run
npm run build
```

Backend integration tests refuse to run unless `TEST_DATABASE_URL` points to the PostgreSQL database named exactly `carrier_intelligence_hub_test`. Test records are isolated with transactions.

## Application behavior

Agents see their assigned cases, tasks, and review work. Managers inherit those capabilities and can also inspect agency workload, manage carrier/domain/sender whitelists, view analytics, and review structured audit logs. The backend enforces every ownership and role boundary; frontend route guards are only a user-experience layer.

Authentication uses an HttpOnly cookie containing an opaque random session token. PostgreSQL stores only its SHA-256 lookup hash, session state, and a CSRF-token hash. Passwords are stored only as Argon2id hashes. See [authentication](docs/authentication.md), [data model](docs/data-model.md), and [architecture](docs/architecture.md).

## Current boundary

Implemented now: login/logout, Agent/Manager authorization, database-backed sessions, CSRF defense, seeded operational records, cases, tasks, reviews, carrier configuration, analytics, and audit history.

Not implemented yet: Gmail OAuth, credential encryption, mailbox polling/webhooks, attachment download, PDF extraction, live AI classification/extraction, CRM integrations, invitations, or production deployment. Seeded carrier messages are development fixtures delivered through the same database and API paths the future ingestion pipeline will use.
