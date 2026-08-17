# Architecture

## Data flow

```
User (browser)
   |
   |  st.login() — Google OIDC
   v
Streamlit app (app/Home.py, app/pages/*.py)
   |
   |--- OpenAlex REST API ---------> paper search results
   |--- Databricks FM API ---------> chat (agent, summaries), embeddings
   |--- Lakebase (Postgres+pgvector) -> everything persisted
```

Every read/write to the database goes through `src/research_copilot/repositories/` — page code and the agent never issue raw queries directly. `src/research_copilot/db.py` owns connection setup and picks one of three paths, in order:

1. `DATABASE_URL` set → plain Postgres connection (local dev, tests, or Lakebase reached with a native role — see [Database connection](#database-connection) below)
2. Databricks OAuth profile + Lakebase instance name → short-lived credential minted per connection, auto-refreshed
3. `LAKEBASE_STATIC_TOKEN` → a hand-pasted token good for ~1 hour, manual-check escape hatch only

## Database connection

Lakebase supports two authentication shapes: short-lived OAuth credentials tied to a Databricks identity, and native Postgres roles with a real password. This app uses the second for its actual running connection — a role named `app_user`, with a password, connected to via a plain `DATABASE_URL` exactly like local Postgres. That keeps the connection code identical between local dev and Lakebase and avoids needing token-refresh logic in the request path.

The OAuth-credential path (`db.py`'s `_build_lakebase_credential_creator`) still exists and works, and is the better fit for a deployed app authenticating as a service principal rather than a personal login — it's just not what this app's own runtime connection uses today.

**`load_dotenv(override=True)`**, not the default `load_dotenv()`: every page and `tests/conftest.py` calls it with `override=True`. Without that, a `DATABASE_URL` already exported in the shell silently wins over `.env` — `python-dotenv` doesn't overwrite an existing environment variable by default — which is a confusing way to end up writing to the wrong database with no error at all.

## Schema

9 core tables, plus 4 for the Study Buddy mode and 1 reserved for future full-text ingestion. `papers.id` and `authors.id` are OpenAlex IDs used directly as primary keys, so re-fetching a work is a natural upsert rather than a dedupe step.

| Table | Purpose | Notable constraints |
|---|---|---|
| `users` | One row per Google identity | unique `google_sub` |
| `learning_goals` | A search *is* stating a learning goal — created/reused on every logged-in search | dedup on case-insensitive title match per user |
| `papers` | Cached OpenAlex works | HNSW index on `embedding` (`vector_cosine_ops`) |
| `authors` | Cached OpenAlex authors | |
| `paper_authors` | Paper↔author join, with position | |
| `collections` | A user's saved paper set, optionally linked to the goal that prompted it | name ≤300 chars, description ≤5000 chars |
| `collection_papers` | Collection↔paper join, ordered | |
| `reading_progress` | Per-user, per-paper, per-collection status | `status` enum, `progress_pct` 0–100, unique per (user, paper, collection) |
| `notes` | Free text, scoped to a paper, a collection, or both | at least one scope required; content ≤20000 chars |
| `paper_chunks` | Reserved for v1.1 full-text ingestion | not written to in v1 |
| `study_concepts`, `concept_explanations`, `concept_evidence`, `comprehension_checks` | Study Buddy's per-concept explanation journey | see `study_buddy.py` |

HNSW was chosen over ivfflat for the papers embedding index specifically because ivfflat needs representative data present *before* the index is built to cluster well — a bad fit for a cache that grows one search at a time. HNSW builds incrementally.

Length constraints on `collections.name`/`description` and `notes.content` are defense in depth, not the primary guard — the UI already caps input (`max_chars` on the relevant `st.text_input`/`st.text_area` calls) — but a DB-level `CHECK` means a bypassed or forgotten app-level check still can't write an unbounded string.

## Agent tools

`src/research_copilot/agent.py` implements a standard tool-calling loop against the OpenAI-compatible chat endpoint. Six tools:

| Tool | Does |
|---|---|
| `search_papers` | Searches OpenAlex directly |
| `list_collection_papers` | Lists papers in a collection |
| `retrieve_evidence` | Pulls a relevant snippet from a paper's abstract |
| `generate_reading_plan` | Runs the 3-stage sequencing algorithm over a collection |
| `add_to_collection` | Adds a paper to a collection |
| `recommend_next` | Recommends the next unread paper in reading order |

Every tool that takes a `collection_id` calls `_require_owned_collection` first, which raises `ToolAuthorizationError` if the collection doesn't belong to the calling user. `_dispatch` passes `user_id` through to each of these — the agent cannot be prompted into reading or writing another user's collection, papers, or notes.

Each tool call in `run_agent`'s loop runs inside its own `session.begin_nested()` (a SAVEPOINT). Without this, one failed tool call (e.g. a bad `paper_id` causing a `ForeignKeyViolation`) would poison the whole transaction and cause every subsequent tool call in the same turn to fail too, even unrelated ones.

## Security model

- **Least privilege**: the app's own database role (`app_user`, see `lakebase_app_user_grants.sql`) has `SELECT`/`INSERT`/`UPDATE`/`DELETE` only — no `CREATE`/`ALTER`/`DROP`. Schema migrations run under a separate, owner-level connection. `tests/test_least_privilege.py` proves this against a real restricted role, not just by reading the grant statements.
- **IDOR protection**: every collection-scoped read/write (`get_owned_collection`, and the agent's `_require_owned_collection`) checks `collection.user_id == requesting_user.id` before returning or mutating anything. Found via a systematic grep audit of every `get_collection`/`list_papers_in_collection` call site.
- **SQL injection resistance**: all queries go through SQLAlchemy's parameterized query building — no raw string interpolation into SQL anywhere in the repositories. `tests/test_security.py` stores real injection payloads as literal data and confirms they never execute.
- **Transaction safety**: two distinct bugs were found and fixed this way, both in the same general family (a write silently not landing) but with different mechanisms:
  1. *Agent tool-call poisoning* — fixed with per-tool-call SAVEPOINTs (`session.begin_nested()`), described above.
  2. *`st.rerun()` racing a pending commit* — Streamlit's `st.rerun()` raises `RerunException`, which inherits from `BaseException`, not `Exception` (deliberately, so it can't be caught by user `try/except Exception` blocks). If `st.rerun()` fires while still inside a `with session_scope():` block, `session_scope`'s own `except Exception:` doesn't catch it either — the block's `session.commit()` line is never reached, and the session just closes, silently discarding the write. Fixed by giving every write-then-rerun call site its own `session_scope()` that closes (and commits) *before* `st.rerun()` is called, never a shared session that's still open when the rerun fires.

## Theming

`src/research_copilot/theme.py` implements light/dark mode and panel backgrounds entirely as injected CSS driven by `st.session_state`, not Streamlit's native `[theme]` config in `.streamlit/config.toml`. That config is server-wide — flipping it at runtime would change the theme for every logged-in user's session at once, not just the one who clicked the toggle.

Two mechanisms:
- `st.container(key="panel-tint-<1-4>")` wraps a whole panel; `theme.py` styles it via the `.st-key-panel-tint-<n>` class Streamlit generates from `key=`. All four tints are the same hue (the app's teal primary color) at different lightness steps, not four unrelated colors.
- `st.container(border=True, key=f"card-<label>-<id>")` wraps one card; styled via an `[class*="st-key-card-"]` substring selector so every card gets the same treatment without a fixed key per page.

## Testing

`uv run pytest` — 44 tests as of this writing. Database-backed tests are skipped automatically without `DATABASE_URL`; tests marked `integration` hit real external services (OpenAlex; Databricks FM APIs, gated separately by `requires_fm_api`). All DB-backed tests use a transaction that's rolled back at the end (`tests/conftest.py`'s `db_session` fixture), so running the suite against real Lakebase leaves no residue — proven live, not assumed.
