# AGENTS.md

Guidance for AI coding agents in this repository.

## Layout

- Monorepo with three independently verified areas; CI is path-filtered per area (`core/**`, `indexer/**`, `docs/**`):
  - `core/` — one container image: Vue 3 webcomponent (`core/frontend`) built into the FastAPI backend (`core/backend`), served on port 8080 (CI: `.github/workflows/core-ci.yml`).
  - `indexer/` — offline collect/transform/embed/Qdrant-index job with its own image (CI: `indexer-ci.yml`).
  - `docs/` — VitePress site with its own `package.json` (`npm run docs:dev/build/lint`), deployed to GitHub Pages from `main`. `docs/de/` holds German translations; update the counterpart when editing docs content.
- Architecture, data flow, and runtime lifecycle: `docs/architecture.md`. Common failures table: `docs/local-development.md`.

## Verify changes (mirrors CI)

```bash
# Backend
cd core/backend && uv sync --locked && uv run ruff check . && uv run pytest
# Frontend
cd core/frontend && npm ci && npm run lint && npm run build
# Indexer
cd indexer && uv sync --locked && uv run ruff check . && uv run pytest
```

## Toolchain

- Python is pinned exactly to 3.13.11 (`requires-python = "==3.13.11"`, `.python-version`). Use `uv` and `uv sync --locked`.
- Node 24 is required (`engines.node = "=24.x"`); npm for frontend and docs.
- All dependency versions are exactly pinned (`==` in pyproject, exact npm versions). Renovate opens update PRs — do not loosen ranges or hand-edit lockfiles.

## Core backend gotchas

- Importing `backend.py` (directly or via tests) fails at import time unless `DLF_SESSION_SECRET`, `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_HOST` are set (`envtools.getenv_with_exception`). `core/backend/.env.example` does not include them — copying it is not enough to run the server.
- `core/backend/tests/test_app.py` sets those variables itself before importing `backend`; keep that env setup above the import when adding tests.
- `core/backend/app.py` and `indexer/app.py` call `truststore.inject_into_ssl()` and `load_dotenv()` before all other imports (corporate TLS interception). The `# ruff: noqa: E402` header only tolerates imports below that block — keep the ordering.
- The backend serves `core/backend/static/`. Without a frontend build it serves a placeholder page. `npm run buildlocal` (in `core/frontend`) builds and copies `dist/` into `core/backend/static/`.

## Frontend

- `npm run lint` = prettier --check + eslint + `vue-tsc --noEmit`; `npm run fix` autofixes both.
- `npm run dev` serves only the frontend on http://localhost:8082/ (API base via `VITE_VUE_APP_API_URL`, fallback same origin — see `src/util/constants.ts`); combine with the backend for a full app on 8080.
- Vitest is configured but there is no `test` script and no test files; frontend CI runs lint + build only.

## Environment & Compose

- `compose.yaml` fails unless `core/backend/.env` and `indexer/.env` exist (`env_file: required: true`) — copy the `.env.example` files first. `.env` is gitignored; never commit real values (pre-commit runs gitleaks).
- `docker compose up --build core` starts Qdrant (6333) + core (8080, health at `/api/healthz`). The indexer mutates Qdrant data and is profile-gated: `docker compose --profile indexer run --rm indexer`.
- Embedding/vector configuration must match between core and indexer (`OPENAI_EMBEDDING_MODEL`, `EMB_SPARSE_MODEL`, `VDB_DENSE_VECTOR_NAME`, `VDB_SPARSE_VECTOR_NAME`); a mismatch makes indexed data incompatible with search (`docs/architecture.md`).

## Ruff config split

- `indexer/` has its own `[tool.ruff]` in `indexer/pyproject.toml` (line length 120, target py313).
- `core/backend/` has no local config, so the root `ruff.toml` applies (line length 140, target py313).
- Pre-commit (repo root) runs ruff check --fix, ruff format, JSON/YAML checks, and gitleaks on all files.

## Releases

- Tag pushes `core-vX.Y.Z` / `indexer-vX.Y.Z` publish `ghcr.io/it-at-m/dienstleistungsfinder-ki-core` / `-indexer` (plus `sha-<commit>` tags, SBOM, provenance). Deployments pin reviewed versions and immutable digests, never `latest`.
