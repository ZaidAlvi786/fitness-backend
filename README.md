# Momentum Backend

Server-side for the Momentum fitness app. **Separate from the Android app** (`../fitness-app`) on
purpose: it owns only what must live server-side — the shared Postgres schema, and (later) the
FastAPI service for secret-bearing work (LLM coaching), heavy aggregation, and integrations.

## Service boundary
- **Supabase** owns auth (issues JWTs), the Postgres database, RLS, realtime, storage, and the
  Android client's direct CRUD.
- **This project** owns:
  - `supabase/` — the database schema + RLS migrations (the source of truth for the shared DB).
  - `app/` — the FastAPI service (added in a later phase). Verifies Supabase JWTs (RS256 via JWKS),
    holds the Anthropic/OpenAI keys, exposes coaching + aggregation endpoints.

The Android client and this backend share **one identity system**: Supabase issues the JWT; Postgres
RLS and the FastAPI service both verify it. The **service-role key is never on the client** — only here.

## Structure
```
fitness-backend/
  supabase/migrations/                  # DB schema + RLS (source of truth for the shared Postgres)
  app/
    core/        config.py · security.py (JWT/JWKS) · errors.py · logging.py
    db/          session.py (RLS-scoped) · models.py
    schemas/     auth · coaching · aggregation · common  (Pydantic v2)
    repositories/activity_repository.py
    services/    coaching_service · aggregation_service · rate_limit · llm/provider.py
    api/         deps.py · v1/{coaching,aggregation,health,router}.py
    main.py      app factory (lifespan, middleware, CORS, handlers)
  tests/         test_auth · test_validation · test_coaching
  pyproject.toml · .env.example
```

## Running the FastAPI service

```bash
# from fitness-backend/
uv sync --extra dev            # or: pip install -e ".[dev]"
cp .env.example .env           # fill SUPABASE_URL, DATABASE_URL, GEMINI_API_KEY
uv run uvicorn app.main:app --reload
# docs at http://localhost:8000/docs (disabled in production)

uv run ruff check . && uv run mypy app && uv run pytest
```

### Endpoints
- `GET /health`, `GET /ready` — unauthenticated probes.
- `POST /api/v1/coaching/insights` — JWT-gated, per-user rate-limited. Takes summarized activity,
  returns AI insights (Anthropic key server-side; LLM output validated before return).
- `GET /api/v1/aggregation/trends?days=30` — JWT-gated; RLS-scoped roll-up from `daily_activity`.

### How it upholds the boundary
- **Auth:** every protected route depends on `get_current_user`, which verifies the Supabase JWT
  (RS256) against the cached JWKS — signature, `exp`, and `aud`. One identity system, shared.
- **RLS on a direct connection:** `get_user_session` sets `request.jwt.claims` + the `authenticated`
  role LOCAL to each transaction, so `auth.uid()` policies apply exactly as via PostgREST — no
  service-role key, no hand-rolled user filtering.
- **LLM safety:** keys live only in settings; only summarized aggregates are sent; the model's output
  is parsed/validated against a Pydantic schema before it can reach the client.

## Applying the schema

**Option A — Supabase CLI (recommended, version-controlled):**
```bash
# from fitness-backend/
supabase init                 # if not already initialized (creates supabase/config.toml)
supabase link --project-ref <your-project-ref>
supabase db push              # applies everything in supabase/migrations/
```

**Option B — manual:** paste the contents of `supabase/migrations/20260606000000_init_schema.sql`
into the Supabase Dashboard → SQL Editor → Run.

## What the schema gives you
- `profiles` (1:1 with `auth.users`), `sessions`, `step_records` — all **RLS-scoped to `auth.uid()`**,
  so a client only ever sees/writes its own rows.
- Domain invariants enforced in the DB (e.g. a COMPLETED session must have an `end_millis ≥ start_millis`).
- `daily_activity` — a `security_invoker` view that rolls up steps per day; the seam the FastAPI
  aggregation endpoint will read with the user's JWT (heavy aggregation stays in Postgres).

## Deploying to Render (free tier)

A [`render.yaml`](render.yaml) Blueprint is included. The free web service sleeps after ~15 min idle
(~30s cold start on the next request) — fine for dev/demo. **See [DEPLOY_RENDER.md](DEPLOY_RENDER.md)
for the full step-by-step guide** (secrets, pooler DSN, verification, troubleshooting); the summary
below is the short version.

1. Push this repo to GitHub.
2. Render Dashboard → **New → Blueprint** → pick the repo. It reads `render.yaml`.
3. Set the secret env vars when prompted (marked `sync: false`): `SUPABASE_URL`, `DATABASE_URL`,
   `GEMINI_API_KEY`, and optionally `CORS_ORIGINS` / `SENTRY_DSN`.
4. Deploy. Health check is `GET /health`; once live, verify the DB with `GET /ready`.

**⚠️ Use the Supabase _Session_ pooler for `DATABASE_URL` on Render**, not the direct
`db.<ref>.supabase.co` host — that host is IPv6-only and Render egresses over IPv4, so the direct
DSN will time out. Grab the Session-pooler URI from Supabase → **Connect** (port `5432`, user
`postgres.<project-ref>`), and keep the `postgresql+asyncpg://` prefix:

```
DATABASE_URL=postgresql+asyncpg://postgres.<ref>:PASSWORD@aws-0-<region>.pooler.supabase.com:5432/postgres
```

Use **Session** mode, not Transaction (`6543`) — Transaction mode breaks the per-request
`SET LOCAL ROLE` that this app's RLS relies on ([app/db/session.py](app/db/session.py)).

## Dashboard prerequisites (one-time)
- **Auth → Providers:** enable Email (disable "Confirm email" for the current signup→profile flow)
  and Google (add the OAuth client + redirect `com.auratech.momentum://login-callback`).
- **Settings → JWT / Signing Keys:** enable **asymmetric (RS256) signing keys** so the FastAPI
  service can verify tokens via the public JWKS endpoint.
