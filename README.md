# Dienstleistungsfinder KI

Dienstleistungsfinder KI is a retrieval-augmented search application for public services. This public monorepo contains the application code and publishes two independently versioned container images.

## Architecture

- `core/frontend`: Vue web component, built with Node.
- `core/backend`: FastAPI API, integrated FastMCP server at `/mcp`, and static-file server.
- `core/Dockerfile`: multi-stage image that builds the frontend and serves it with the backend on port 8080.
- `indexer`: opt-in collection, transformation, embedding, and Qdrant indexing job.
- `compose.yaml`: local core and Qdrant environment; the indexer is behind the `indexer` profile.

OpenShift manifests, secrets, schedules, environment-specific endpoints, and deployment promotion remain in the private infrastructure repository. This repository does not contain deployment credentials or build application images in GitLab CI.

## Local development

Requirements are Docker, Python 3.13 with [uv](https://docs.astral.sh/uv/), and Node.js 24.

```shell
cp core/backend/.env.example core/backend/.env
cp indexer/.env.example indexer/.env
docker compose up --build core
```

The UI is at `http://localhost:8080/`, health is at `http://localhost:8080/api/healthz`, and the integrated FastMCP endpoint is at `http://localhost:8080/mcp`. MCP clients use Streamable HTTP; only the retrieval tool is exposed by default. See [MCP integration](docs/mcp-server.md) for configuration. Run the external indexer only when its required secrets and endpoints are configured:

```shell
docker compose --profile indexer run --rm indexer
```

When running the backend directly instead of through Compose, first build the
frontend into the backend's static directory:

```shell
cd core/frontend && npm ci && npm run buildlocal
cd ../backend && uv sync && uv run python app.py
```

Running only `core/backend/app.py` without `npm run buildlocal` serves a
placeholder page at port 8080. For frontend-only hot reload, use `npm run dev`
and open `http://localhost:8082/`.

For component checks:

```shell
cd core/backend && uv sync && uv run ruff check .
cd core/frontend && npm ci && npm run lint && npm run build
cd indexer && uv sync && uv run ruff check . && uv run pytest
```

## Configuration

Copy the committed `.env.example` files to ignored `.env` files. Never commit real values. The core requires the model, embedding, and Qdrant settings used by the selected features. The indexer requires `QDRANT_URL`, `QDRANT_API_KEY`, and its embedding configuration. `API_AUTH_USER` and `API_AUTH_PASS` enable authenticated API-ID retrieval. Etracker enrichment runs only when both `ETRACKER_URL_BASE` and `ETRACKER_TOKEN` are present; otherwise it is logged as skipped.

## Images and releases

- `ghcr.io/it-at-m/dienstleistungsfinder-ki-core:<version>` from `core-vX.Y.Z`
- `ghcr.io/it-at-m/dienstleistungsfinder-ki-indexer:<version>` from `indexer-vX.Y.Z`

Release workflows also publish `sha-<commit>` tags, SBOMs, and provenance. Deployments must pin a reviewed version and immutable digest, never `latest`. After the first release, maintainers must set both GHCR packages to public visibility.

## Contributing and license

See [CONTRIBUTING.md](CONTRIBUTING.md) and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). The project is licensed under the [MIT License](LICENSE).
