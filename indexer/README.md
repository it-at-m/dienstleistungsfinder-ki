# DLF Indexer

Offline job that collects public municipal content, transforms it, generates dense and sparse embeddings, and upserts the result into the Qdrant vector database used by the core search.

## What it does

1. Builds documents for the configured collections (`VDB_COLLECTIONS`, e.g. `service,info`): structured service articles and Magnolia info pages.
2. Optionally enriches service articles with eTracker visit statistics; enrichment is skipped unless both `ETRACKER_URL_BASE` and `ETRACKER_TOKEN` are set.
3. Embeds documents and upserts them into Qdrant.

Abort conditions:

| Exit code | Cause                                                        |
| --------- | ------------------------------------------------------------ |
| `2`       | `QDRANT_URL` or `QDRANT_API_KEY` missing                     |
| `3`       | Qdrant connection failed                                     |
| `255`     | Fewer than `DLF_INDEXER_MIN_ARTICLES` (default 800) articles |

Set `SAVE_ARTICLES=1` to dump collected articles to `artifacts/articles.jsonl` for inspection.

## Run

Configuration comes from `indexer/.env` (copy from `.env.example`). The indexer needs a `QDRANT_API_KEY` with write permissions; the core uses a separate read-only credential.

Via Compose against the local Qdrant:

```shell
docker compose --profile indexer run --rm indexer
```

Directly:

```shell
uv sync --locked
uv run python app.py
```

The embedding/vector configuration must match the core (see `docs/architecture.md`); a mismatch makes indexed data incompatible with search.

More details: [indexing pipeline](../docs/indexing-pipeline.md).
