# System architecture

The system is split into an offline write path and an online read path. Both use the same embedding configuration and Qdrant vector names; changing those values on only one side makes indexed data incompatible with search.

## Component view

| Component       | Technology           | Runs as                           | Main dependency                             |
| --------------- | -------------------- | --------------------------------- | ------------------------------------------- |
| Search UI       | Vue 3 custom element | Static browser assets             | Core HTTP API                               |
| Core API        | FastAPI, LangChain   | Long-running service on port 8080 | Qdrant, OpenAI-compatible API, Langfuse     |
| MCP server      | MCP Python SDK       | Long-running service on port 8080 | Core retrieval API                          |
| Indexer         | Python, LangChain    | On-demand or scheduled job        | Content APIs, Qdrant, OpenAI-compatible API |
| Vector database | Qdrant               | Long-running service on port 6333 | Persistent volume                           |

The core container is a multi-stage image. Node builds the frontend first; the resulting static assets are copied into the Python runtime image and mounted by FastAPI at `/`. API routes remain under `/api`.

## Data flow

```text
Municipal service APIs ──► Indexer ──► dense + sparse vectors ──► Qdrant
                                                                    │
Browser ──► Vue web component ──► FastAPI ──► hybrid retrieval ─────┘
                                  │
                                  ├──► OpenAI-compatible models
                                  └──► Langfuse traces and feedback

MCP client ──► MCP server ──► FastAPI retrieval API ────────────────┘
```

The MCP server is a thin agent-facing adapter. It exposes one read-only retrieval tool and delegates searching to the Core API; it does not connect to Qdrant or model providers directly.

The `service` collection contains structured public-service articles. The `info` collection contains Magnolia information pages. `VDB_COLLECTIONS` controls which builders run in the indexer and which collections the backend opens.

## Why two vector types?

Dense embeddings represent semantic similarity: differently worded questions can still be close in vector space. Sparse BM25 vectors preserve exact lexical matches, which is valuable for administrative terms, form names, and uncommon identifiers. Qdrant fuses both result sets before optional reranking.

<img class="diagram light-only" src="./graphics/HowDoEmbeddingsWork_en.png" alt="How text is converted into embeddings and compared">
<img class="diagram dark-only" src="./graphics/HowDoEmbeddingsWork_en_dark.png" alt="How text is converted into embeddings and compared">

<img class="diagram light-only" src="./graphics/HybridSearch_en.png" alt="Dense and sparse retrieval combined into hybrid search">
<img class="diagram dark-only" src="./graphics/HybridSearch_en_dark.png" alt="Dense and sparse retrieval combined into hybrid search">

## Runtime lifecycle

FastAPI's lifespan hook initializes the application in this order:

1. Connect Langfuse and load prompt templates.
2. Construct the reranker.
3. Create chat, dense embedding, and sparse BM25 models.
4. Open a Qdrant vector store for every configured collection.
5. Compose query-enhancement, retrieval, reranking, answer, and scrubber chains.
6. Optionally start the background popularity-statistics refresh.
7. Load keyword and category filters from Qdrant metadata or fallback files.

At shutdown, the popularity task is cancelled and remaining Langfuse events are flushed.

## Trust and privacy boundaries

- The browser holds only runtime UI state and a signed session cookie.
- Optional query scrubbing runs before retrieval; clients should use the returned scrubbed text downstream.
- Qdrant contains normalized public content, metadata, vectors, and optional visit statistics.
- Model and observability calls leave the application boundary and must use approved endpoints.
- Secrets are injected through environment variables and must never be committed.

## Design constraints

The same dense model, sparse model, vector names, and dimensions must be used for indexing and retrieval. Stable UUIDv5 document IDs let the indexer update changed content instead of creating duplicates. The core is read-oriented and can use a read-only Qdrant key, while the indexer requires write access.
