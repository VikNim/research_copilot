# Research Copilot

An AI research and learning copilot. State a topic in plain language, discover papers via OpenAlex, save them into collections, and get an agent-built, sequenced reading plan — foundational papers first, then the review that ties them together, then current applications.

Built as a Streamlit app on top of Databricks Lakebase (managed Postgres + pgvector) and Databricks Foundation Model APIs.

## Features

**Discovery & search**
- Live paper search against the OpenAlex API from a plain-language learning goal, not keywords
- Sort by citations, date, title, or semantic match (vector similarity over abstract embeddings, not keyword overlap)
- Every search result is cached into Postgres on first sight, so re-ranking or reopening a paper never re-fetches it

**Workspace**
- Three-panel layout: matching papers, reading pane (abstract or an AI-generated summary), and an in-progress collection
- Per-paper actions (read, summarize, add to collection, discard) behind a compact menu
- Save a collection and it's automatically linked back to the learning goal that prompted it

**Agent**
- A tool-calling agent (Claude Haiku 4.5 via Databricks) scoped to one collection at a time
- Six tools: search papers, list a collection's papers, retrieve evidence from an abstract, generate a reading plan, add a paper to a collection, recommend what to read next
- Every tool call that touches a collection checks ownership first — the agent can't be steered into reading or writing another user's data

**Reading plans & tracking**
- Three-stage sequencing (review → foundational → current) using citation graph position, publication year, and an LLM-scored jargon-density signal
- Self-reported reading progress per paper (not started / in progress / done)
- Notes at the paper level and the collection level

**Auth**
- Google sign-in via Streamlit's native OIDC support (`st.login()`) — open self-serve signup, not gated to a Databricks workspace
- A new Google identity is provisioned as an app account automatically on first login; there's no separate signup step

**Appearance**
- Light/dark toggle, scoped per browser session (not a server-wide setting)
- Panels tinted in one hue at four lightness steps so the workspace's three panels and the profile page's sections are visually distinct without looking like a color chart

## Tech stack

| Layer | Choice |
|---|---|
| App framework | Streamlit (multipage, `st.login()` for auth) |
| Database | Databricks Lakebase — managed Postgres 17 with native pgvector (one store for relational data and vector search) |
| LLM | Claude Haiku 4.5, via Databricks Foundation Model APIs (OpenAI-compatible surface) |
| Embeddings | Qwen3-Embedding-0.6B, via the same Databricks FM API surface |
| Papers | OpenAlex REST API, called directly (no wrapper/MCP layer) |
| ORM | SQLAlchemy 2.0 (declarative models, typed `Mapped[...]` columns) |
| Package/env management | `uv` |

## Project structure

```
app/
  Home.py                 # Screen 1 — landing page, search box
  pages/
    1_Workspace.py         # Screen 2 — matching papers / reading pane / collection
    2_Profile.py            # Screen 3 — collections index + collection detail
src/research_copilot/
  agent.py                 # tool-calling agent + tool schemas
  auth.py                  # st.login()/st.logout() wrapper, header, theme toggle
  config.py                # Settings — every env var the app reads
  db.py                    # engine/session setup (local Postgres or Lakebase)
  models.py                 # SQLAlchemy ORM models (schema)
  theme.py                  # light/dark mode + panel CSS
  openalex_client.py        # OpenAlex REST client
  llm.py / embeddings.py    # Databricks FM API calls
  databricks_auth.py        # bearer-token resolution for the FM API
  semantic.py                # embed-on-demand + cosine-similarity ranking
  sequencing.py              # reading-plan stage algorithm
  study_buddy.py             # second, separate conversational mode (backend only — no UI page yet)
  validation.py               # search input validation
  repositories/                # one module per table family — all DB reads/writes go through these
tests/                          # pytest — see "Running tests" below
docs/ARCHITECTURE.md            # schema reference, agent tools, security model, theming
lakebase_app_user_grants.sql    # GRANT statements for the least-privilege app_user role
```

## Getting started

### Prerequisites
- Python 3.12+
- [`uv`](https://docs.astral.sh/uv/)
- PostgreSQL 17 with the `pgvector` extension, for local development (Homebrew: `brew install postgresql@17 pgvector`)
- A Google Cloud OAuth app, for login (see below)
- A Databricks workspace with Lakebase and Foundation Model API access, for the database and the agent/embeddings — the app runs without these but search-only, no saving, no summaries, no agent

### 1. Install dependencies
```bash
uv sync
```

### 2. Configure environment
```bash
cp .env.example .env
```
Edit `.env`. Two database paths are supported — pick one:
- **Local dev**: `DATABASE_URL=postgresql+psycopg://localhost:5432/research_copilot_dev` (works with the Homebrew Postgres above)
- **Lakebase**: point `DATABASE_URL` at Lakebase's host using a native Postgres role (`app_user`) rather than a short-lived OAuth credential — see `.env.example` for the exact form and `docs/ARCHITECTURE.md` for why.

Also fill in `DATABRICKS_FM_BASE_URL` and either `DATABRICKS_PROFILE` (OAuth, no PAT needed) or `DATABRICKS_FM_TOKEN`, to enable the agent, summaries, and semantic search.

### 3. Set up the database
Local Postgres:
```bash
createdb research_copilot_dev
```
Then let the app create the schema on first run (`init_db()` runs automatically when `DATABASE_URL` is set locally), or run it explicitly:
```bash
uv run python -c "from research_copilot.db import init_db; init_db()"
```

Lakebase: the schema is migrated by an owner-level connection, not the app's own least-privilege role. See `lakebase_app_user_grants.sql` and `docs/ARCHITECTURE.md`.

### 4. Set up Google login
```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
```
Fill in `client_id`/`client_secret` from a Google Cloud OAuth app (type: Web application; authorized redirect URI matching `redirect_uri` in the file) and a random `cookie_secret`.

### 5. Run it
```bash
uv run streamlit run app/Home.py
```

## Running tests

```bash
uv run pytest
```

Database-backed tests are skipped automatically if `DATABASE_URL` isn't set; live-API tests (OpenAlex, Databricks FM) are marked `integration` and need real network/credentials. Point `DATABASE_URL` at Lakebase to run the suite against it — set `SKIP_DB_INIT=1` first, since the app's own database role deliberately can't run schema DDL:

```bash
SKIP_DB_INIT=1 uv run pytest
```

## Documentation

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the full database schema, the agent's tool reference, the security model (least-privilege DB role, ownership checks, transaction safety), and the theming system.

## Known limitations (v1)

- Abstracts only — no full-text PDF ingestion or rendering yet (`paper_chunks` table exists, reserved for v1.1)
- Reading progress is self-reported, not scroll/page tracked (Streamlit can't observe scroll position in externally hosted content)
- No proactive "since you added X, read Y first" suggestions yet
- Study Buddy (a second, ELI5-layered conversational mode) has working backend logic and tests but no UI page yet
