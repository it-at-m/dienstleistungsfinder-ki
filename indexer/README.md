# DLF Indexer

Offline job that collects public municipal content, transforms it, generates dense and sparse embeddings, and upserts the result into the Qdrant vector database used by the core search.

## What it does

1. Builds documents for the configured collections (`VDB_COLLECTIONS`, e.g. `service,info`): structured service articles and Magnolia info pages.
2. Optionally enriches service articles with eTracker visit statistics; enrichment is skipped unless both `ETRACKER_URL_BASE` and `ETRACKER_TOKEN` are set.
3. Optionally exports the transformed, vector-free `service` and `info` documents to separate Hugging Face datasets.
4. Embeds documents and upserts them into Qdrant.

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

## Hugging Face Dataset Export

Set `HF_DATASET_EXPORT_ENABLED=true` and provide `HF_TOKEN` with write access to both existing datasets to publish the transformed content before embeddings are generated:

| Collection | Dataset repository |
| ---------- | ------------------ |
| `service`  | `it-at-m/munich-city-services` |
| `info`     | `it-at-m/munich-city-info` |

The exporter replaces each repository's `default` configuration `train` split. It exports document metadata, the stable `document_id`, and Markdown `content`; it does not generate, read, or publish dense or sparse vectors. A configured export that fails prevents Qdrant loading, so both published datasets and the vector index reflect the same successful source collection.

The repositories must be provisioned separately. See [Hugging Face dataset setup](HUGGINGFACE_SETUP.md) for the one-time `hf` CLI script, dataset cards, access requirements, and the CC BY 4.0 license decision.

More details: [indexing pipeline](../docs/indexing-pipeline.md).
