# Local development

The quickest complete environment uses Docker Compose. Direct development is useful when changing only the backend or frontend.

## Prerequisites

- Docker with Compose support
- Python 3.13 and `uv` for direct Python development
- Node.js 24 and npm for frontend or documentation work
- Credentials for the configured OpenAI-compatible and Langfuse endpoints

## Configure the applications

Create ignored environment files from the committed templates:

```bash
cp core/backend/.env.example core/backend/.env
cp indexer/.env.example indexer/.env
```

The templates are intentionally minimal. The backend code also validates these values during startup:

| Variable                                                      | Purpose                                                                |
| ------------------------------------------------------------- | ---------------------------------------------------------------------- |
| `DLF_SESSION_SECRET`                                          | Signs browser session cookies                                          |
| `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_HOST` | Prompt loading, tracing, and feedback                                  |
| `OPENAI_API_KEY`, `OPENAI_API_BASE`                           | Chat, embedding, and reranking API access                              |
| `OPENAI_CHAT_MODEL`, `OPENAI_EMBEDDING_MODEL`                 | Runtime model selection                                                |
| `QDRANT_URL`                                                  | Vector database endpoint; Compose overrides it to `http://qdrant:6333` |

Use `QDRANT_READONLY_API_KEY` for the core when the platform provides a read-only credential. The indexer needs `QDRANT_API_KEY` with collection and point write permissions.

::: warning Configuration parity
`OPENAI_EMBEDDING_MODEL`, `EMB_SPARSE_MODEL`, `VDB_DENSE_VECTOR_NAME`, and `VDB_SPARSE_VECTOR_NAME` must match between core and indexer.
:::

## Start the complete stack

```bash
docker compose up --build core
```

Compose starts Qdrant and the core; the core is available at:

- UI: `http://localhost:8080/`
- Health: `http://localhost:8080/api/healthz`
- OpenAPI UI: `http://localhost:8080/docs` when `DLF_ENABLE_DOCS=true`
- Qdrant: `http://localhost:6333`

The indexer is behind an explicit profile because it calls external systems and changes Qdrant data:

```bash
docker compose --profile indexer run --rm indexer
```

## Run components directly

Build the frontend into the backend's static directory before starting FastAPI:

```bash
cd core/frontend
npm ci
npm run buildlocal

cd ../backend
uv sync
uv run python app.py
```

Running `core/backend/app.py` without the frontend build serves only the source-tree placeholder. For frontend hot reload:

```bash
cd core/frontend
npm ci
npm run dev
```

Open `http://localhost:8082/`. The development frontend expects the API base URL configured in `src/util/constants.ts`.

## Run quality checks

```bash
cd core/backend
uv sync
uv run ruff check .
uv run pytest

cd ../frontend
npm ci
npm run lint
npm run build

cd ../../indexer
uv sync
uv run ruff check .
uv run pytest
```

## Work on these docs

```bash
cd docs
npm install
npm run docs:dev
```

The development URL is normally `http://localhost:5173`. Validate the production output with `npm run docs:build`, then inspect it with `npm run docs:preview`.

## Common failures

| Symptom                            | Likely cause                                                                                            |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------- |
| Backend exits while importing      | A required session or Langfuse variable is absent                                                       |
| Backend starts but retrieval fails | Qdrant collections are empty, credentials are invalid, or vector configuration differs from the indexer |
| Only a placeholder page appears    | The frontend was not built with `npm run buildlocal`                                                    |
| Indexer exits with status 2        | `QDRANT_URL` or `QDRANT_API_KEY` is missing                                                             |
| Indexer stops after collection     | Fewer than `DLF_INDEXER_MIN_ARTICLES` service articles were returned                                    |
| Browser blocks calls               | The origin is not included in comma-separated `DLF_ALLOWED_ORIGINS`                                     |
