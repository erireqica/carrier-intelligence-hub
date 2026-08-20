# Carrier Intelligence Hub

Carrier Intelligence Hub is an authenticated internal operations application for insurance agencies. It automatically turns approved carrier communications into durable policy cases, assigned work, review items, verified evidence, audit history, and Gmail workflow labels. PDF extraction and structured OpenAI analysis remain behind deterministic validation and human review; bounded retries and independent workers make the full path recoverable.

## Stack

- React, TypeScript, Vite, React Router, TanStack Query, and Tailwind CSS
- FastAPI, Pydantic, SQLAlchemy 2, Alembic, and psycopg 3
- PostgreSQL 17
- Argon2id password hashing and database-backed browser sessions
- Google OAuth 2.0, encrypted Gmail tokens, and separate polling/processing/label workers
- PyMuPDF extraction and OpenAI Responses API Structured Outputs
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

## Gmail development setup

This project uses a Google OAuth app in development/testing mode. In Google Cloud, enable the Gmail API, configure the Google Auth Platform as **External** with testing status, add the intended Google account as a test user, and create an OAuth 2.0 **Web application** client. Register this exact redirect URI:

```text
http://localhost:8000/api/v1/gmail/oauth/callback
```

Add these values only to the ignored `backend/.env`; never commit them:

```dotenv
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=
GOOGLE_TOKEN_ENCRYPTION_KEY=
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/api/v1/gmail/oauth/callback
GMAIL_POLL_INTERVAL_SECONDS=60
GMAIL_INITIAL_LOOKBACK_DAYS=7
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.6-terra
AI_AUTO_APPLY_CONFIDENCE_THRESHOLD=0.80
MESSAGE_PROCESS_MAX_AUTO_ATTEMPTS=3
MESSAGE_PROCESS_RETRY_BASE_SECONDS=30
MESSAGE_PROCESS_RETRY_MAX_SECONDS=600
MESSAGE_PROCESS_STALE_AFTER_SECONDS=600
GMAIL_LABEL_MAX_ATTEMPTS=4
GMAIL_LABEL_RETRY_BASE_SECONDS=30
GMAIL_LABEL_RETRY_MAX_SECONDS=600
GMAIL_LABEL_STALE_AFTER_SECONDS=300
```

`GOOGLE_TOKEN_ENCRYPTION_KEY` must be a dedicated Fernet key. Start the API and frontend as above, sign in to Carrier Hub, open **Gmail Connections**, and choose **Connect Gmail** or **Upgrade permissions**. Select the Google account manually and approve `gmail.modify`. This scope is broader than label-only access, but Carrier Hub's adapter exposes only message/attachment reads plus managed-label list, creation, thread inspection, and thread-label modification. It does not expose send, draft, delete, trash, archive, or read-state operations. The application never receives or stores the Gmail password.

## Normal development workflow

Terminal 1 — FastAPI:

```powershell
cd backend
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Terminal 2 — frontend:

```powershell
cd frontend
npm run dev
```

Terminal 3 — combined automated pipeline:

```powershell
cd backend
& .\.venv\Scripts\python.exe -m app.workers.pipeline
```

Use `python -m app.workers.pipeline --once` for one complete poll → process → label pass. For focused debugging, the reusable components remain available as `app.workers.gmail_poll`, `app.workers.message_process`, and `app.workers.gmail_labels`; each supports `--once` and its documented ID filters. Do not run duplicate pollers or pipelines against the same development mailbox unknowingly.

The API starts normally without `OPENAI_API_KEY`; manual analysis returns a safe unconfigured response and the processor exits clearly. To exercise the real provider without database writes, configure the key only in ignored `backend/.env`, then run `python scripts/evaluate_stage4_samples.py`.

Google testing-mode refresh-token policies may require reconnection. The application reports that condition as `NEEDS_REAUTH`; it does not bypass Google's policies. This stage is development-tested and must not be described as Google production verification, a security assessment, HIPAA compliance, SOC 2 compliance, or production authorization approval. Production deployment requires review of Google's applicable OAuth verification, user-data, and security requirements. See [Gmail integration](docs/gmail-integration.md).

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

Implemented now: login/logout, Agent/Manager authorization, database-backed sessions, CSRF defense, cases/tasks/reviews/evidence/audits, carrier configuration, Google OAuth, encrypted Gmail credentials, whitelist-first polling, MIME parsing, in-memory Gmail PDF download, PyMuPDF extraction, strict structured AI proposals, deterministic validation, automatic case/task materialization, human correction or dismissal, bounded message retries, stale-work recovery, and an outbox-based Gmail thread-label projection.

Not implemented yet: OCR, Gmail push notifications, CRM delivery, invitations, or production deployment. Gmail uses polling. Confidence is a review signal, not a calibrated probability. The sender whitelist is not cryptographic SPF/DKIM/DMARC proof, and this development stage makes no production-compliance claim. See [AI processing](docs/ai-processing.md) and [pipeline reliability](docs/pipeline-reliability.md).
