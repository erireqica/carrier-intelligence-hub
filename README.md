# Carrier Intelligence Hub

Carrier Intelligence Hub is an internal insurance operations platform intended to turn carrier communications into structured policy events and actionable work. The repository currently contains the application foundation only; authentication, Gmail, AI processing, and insurance domain features have not been implemented yet.

## Current stack

- Frontend: React, TypeScript, Vite, React Router, TanStack Query, and Tailwind CSS
- Backend: Python 3.14, FastAPI, Pydantic, and pydantic-settings
- Data layer: SQLAlchemy 2, Alembic, psycopg 3, and PostgreSQL 17
- Quality: ESLint, Prettier, Vitest, React Testing Library, Ruff, and pytest

## Repository layout

```text
frontend/   React application and browser tests
backend/    FastAPI application, database foundation, Alembic, and API tests
docs/       Concise architecture documentation
```

## Frontend setup

From PowerShell:

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

The frontend runs at `http://localhost:5173` by default. Its local environment points to the versioned backend API at `http://localhost:8000/api/v1`.

Useful checks:

```powershell
npm run lint
npm run format:check
npm run test
npm run build
```

## Backend setup

From a second PowerShell terminal:

```powershell
cd backend
Copy-Item .env.example .env
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"
& .\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

The API runs at `http://localhost:8000`. Its health endpoint is `GET /api/v1/health`, and interactive API documentation is available at `http://localhost:8000/docs`.

Useful checks:

```powershell
& .\.venv\Scripts\python.exe -m ruff check .
& .\.venv\Scripts\python.exe -m ruff format --check .
& .\.venv\Scripts\python.exe -m pytest
```

## Environment variables

Copy each `.env.example` to `.env` in the same directory. Real `.env` files are ignored by Git.

Frontend:

- `VITE_API_BASE_URL`: versioned FastAPI base URL

Backend:

- `APP_NAME`: service display name
- `ENVIRONMENT`: runtime environment name
- `API_V1_PREFIX`: versioned API prefix
- `FRONTEND_ORIGIN`: allowed browser origin for CORS
- `DATABASE_URL`: SQLAlchemy PostgreSQL connection URL

Never commit passwords, tokens, or OAuth/API credentials.

## PostgreSQL

The local PostgreSQL 17 service was detected on port `5433`. Create the `carrier_intelligence_hub` database and a dedicated application role using credentials managed by the local PostgreSQL administrator. Then put the resulting URL in `backend/.env`:

```text
DATABASE_URL=postgresql+psycopg://APP_USER:APP_PASSWORD@localhost:5433/carrier_intelligence_hub
```

This foundation does not create any tables. Once a domain schema is introduced, Alembic is ready for:

```powershell
cd backend
& .\.venv\Scripts\python.exe -m alembic revision --autogenerate -m "describe schema change"
& .\.venv\Scripts\python.exe -m alembic upgrade head
```

## Next implementation stage

The next logical stage is deliberate design of the first domain schema and internal authentication with Agent/Manager authorization. Gmail ingestion and AI processing should follow incrementally after those controls are established.
