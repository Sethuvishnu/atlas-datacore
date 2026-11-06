# ATLAS DataCore

Independent historical Indian (NSE cash-market) data infrastructure, built to reduce survivorship
bias in backtesting. **Status: Milestone 1 of 13 (foundation).** No market data is imported yet and
no coverage is claimed.

## Quick start (Windows PowerShell)
```powershell
docker compose up -d postgres            # PostgreSQL 16 (+ datacore_test DB)
python -m venv .venv ; .\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
copy .env.example .env
cd backend
alembic upgrade head                      # create schema
python -m pytest                          # tests run against real PostgreSQL (datacore_test)
uvicorn app.main:app --reload             # http://127.0.0.1:8000/docs
```
Health check: `GET http://127.0.0.1:8000/api/v1/health`
(200 when DB is reachable and migrated; 503 `degraded` otherwise).

Linux/macOS: same commands, `source .venv/bin/activate`, `cp`.

## Layout
`backend/app/{config,storage,monitoring,api}`, `backend/migrations` (Alembic), `backend/tests`,
`data/{raw,staging,processed,parquet,exports}` (git-ignored), `scripts/`, `dashboard/` (M11), `docs/`.
Modules for later milestones are intentionally not stubbed.

## Schema conventions
* Identity: `securities` (stable id, ISIN preferred) – ticker is never the sole identity.
* Temporal facts: `valid_from/valid_to` (true in market), `recorded_at` (when DataCore learned it), `source_id`.
* `daily_prices` unique on (security, date, price_type) – raw and adjusted series are separate.
* `raw_data_files` unique on (source, SHA-256) – basis for idempotent re-imports.
* Enums are VARCHAR + CHECK constraints (easy to evolve). Universe snapshots default to completeness `UNKNOWN`.
