---
layout: home

hero:
  name: "Dienstleistungsfinder KI"
  text: "Technical documentation"
  tagline: Retrieval-augmented search for trustworthy information about municipal services.
  actions:
    - theme: brand
      text: Understand the architecture
      link: /architecture
    - theme: alt
      text: Run it locally
      link: /local-development

features:
  - title: Hybrid retrieval
    details: Dense OpenAI embeddings and sparse BM25 vectors search Qdrant collections together.
  - title: Grounded answers
    details: FastAPI retrieval and answer chains connect users to the original municipal source documents.
  - title: Embeddable interface
    details: A Vue custom element packages the complete search experience for use on other websites.
---

## What this project does

Dienstleistungsfinder KI is a retrieval-augmented generation (RAG) application for public-service information. It collects official content, converts it into searchable documents, stores dense and sparse vectors in Qdrant, retrieves candidates for a natural-language question, and can produce an answer grounded in one selected source.

The monorepo publishes two independently versioned applications:

| Application | Location   | Responsibility                                                                            |
| ----------- | ---------- | ----------------------------------------------------------------------------------------- |
| Core        | `core/`    | Vue web component, FastAPI API, integrated FastMCP, retrieval and answer chains, and static-file serving      |
| Indexer     | `indexer/` | Collection, normalization, embedding, Qdrant indexing, and optional popularity enrichment |

Qdrant is the shared boundary between the indexer and Core. The indexer writes collections; Core reads them. FastMCP runs inside Core and exposes its retrieval endpoint to agents. This separation allows indexing to run as a scheduled job without coupling it to user-facing request traffic.

## End-to-end request

1. A user submits a question in the web component.
2. The backend enhances the query, performs hybrid retrieval, and optionally reranks candidates.
3. The frontend requests a grounded answer for each returned document and renders results as they arrive.
4. Positive or negative feedback is attached to the trace in Langfuse.

<img class="diagram light-only" src="./graphics/dlf_rag_en.png" alt="Overall RAG flow from a user's question through hybrid retrieval and answer generation">
<img class="diagram dark-only" src="./graphics/dlf_rag_en_dark.png" alt="Overall RAG flow from a user's question through hybrid retrieval and answer generation">

## Documentation map

- [System architecture](./architecture) explains components, data flow, and search concepts.
- [Local development](./local-development) covers prerequisites, configuration, startup, and checks.
- [Indexing pipeline](./indexing-pipeline) follows content from upstream APIs into Qdrant.
- [Search and API](./search-api) documents runtime chains, endpoints, request flow, and errors.
- [MCP server](./mcp-server) covers agent integration, endpoint configuration and deployment within Core.
- [Frontend and deployment](./frontend-deployment) covers the web component, container build, CI, and releases.

::: tip Scope
Deployment manifests, secrets, environment-specific endpoints, and promotion workflows live in a separate private infrastructure repository. This documentation covers the public application repository.
:::
