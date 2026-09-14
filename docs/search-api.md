# Search and API

The core exposes a FastAPI application and composes LangChain runnables for query enhancement, hybrid retrieval, optional reranking and document-grounded answers.

## Search chain

<img class="diagram light-only" src="./graphics/AnswerChain_en.png" alt="Grounded answer chain for a retrieved document">
<img class="diagram dark-only" src="./graphics/AnswerChain_en_dark.png" alt="Grounded answer chain for a retrieved document">

1. **Enhance:** the chat model rewrites a natural-language question into search-oriented administrative terminology when `enhance_query=true`.
2. **Filter:** exact keywords and categories become Qdrant payload filters. Unknown values are rejected.
3. **Retrieve:** every selected collection performs dense and sparse search; Qdrant fuses candidates using `VDB_RETRIEVAL_FUSION` (default `DBSF`).
4. **Rerank:** when enabled, an OpenAI-compatible Cohere rerank model reorders candidates. Optional visit statistics apply a bounded popularity boost.
5. **Answer:** the answer endpoint loads one selected Qdrant document and asks the model for a response grounded only in that content.

## HTTP endpoints

| Method | Path                    | Operation                                     | Audience              |
| ------ | ----------------------- | --------------------------------------------- | --------------------- |
| GET    | `/api/healthz`          | Process status and application version        | Operations            |
| GET    | `/api/keywords`         | Valid keyword filter values                   | Frontend, MCP clients |
| GET    | `/api/categories`       | Valid category filter values                  | Frontend, MCP clients |
| GET    | `/api/config`           | Examples and feedback templates               | Frontend              |
| POST   | `/api/retrieval`        | Retrieve ranked service documents             | Frontend, MCP clients |
| POST   | `/api/answer`           | Generate an answer from one selected document | Frontend              |
| POST   | `/api/score`            | Attach binary feedback to a Langfuse trace    | Frontend              |
| GET    | `/api/popularity-stats` | Current popularity normalization statistics   | Operations            |

Interactive Swagger and ReDoc are available at `/docs` and `/redoc` unless `DLF_ENABLE_DOCS=false`.

## Typical API flow

First retrieve documents:

```bash
curl -X POST http://localhost:8080/api/retrieval \
  -H 'Content-Type: application/json' \
  -c cookies.txt -b cookies.txt \
  -d '{
    "query": "What documents do I need to register my residence?",
    "enhance_query": true,
    "result": "full",
    "collections": ["service", "info"],
    "rerank": true
  }'
```

The response contains `retrieval_documents`, a `run_id`, and an `enhanced_query`. For the application-specific answer helper, pass the chosen document's `id` and `collection` plus the same query and run identifiers:

```json
{
  "doc": { "id": "<document-id>", "collection": "service" },
  "enhanced_query": { "...": "copy from retrieval response" },
  "run_id": "<run-id>"
}
```

Generic assistants can request `result: "full"` and answer directly from returned `page_content`; they do not need `/api/answer`.

## Retrieval controls

The `RetrievalInput` model supports query enhancement, exact keyword/category filters, collection selection, minimal or full results, reranking, easy-language content, category matching, an optional result count, and an existing `run_id`. Consult the generated OpenAPI schema for the definitive request model of the checked-out revision.

`RERANK_OVERRIDE=true` allows operators to ignore the frontend flag and force the value of `RERANK`. This is an incident-control mechanism for disabling a slow or unavailable reranker without rebuilding the client.

## Errors and observability

- `422` reports invalid request shapes or unknown filter values.
- `404` means the selected document did not yield a grounded answer.
- Model content-policy failures are translated into an explicit API error.

The session cookie groups browser activity; `run_id` correlates retrieval, answer, and score calls. Langfuse callbacks capture chain activity, prompts, latency, and user feedback. Do not log raw secrets or add sensitive user text to custom log statements.

## MCP exposure

`core/backend/settings.py` reads the `MCP_ENDPOINTS` environment setting as a JSON list of method/path objects, for example `[{"method":"POST","path":"/api/retrieval"}]`. Set it in `.env` or the container environment and restart Core. An empty list disables all MCP tools. Only `POST /api/retrieval` is enabled initially; a final exclusion rule prevents all other endpoints from becoming MCP tools or resources. Add an explicit entry to expose another endpoint. For answers grounded in retrieved text, explicitly request `result="full"`.
