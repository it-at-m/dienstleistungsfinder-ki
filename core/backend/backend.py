import asyncio
import os
import time
from contextlib import asynccontextmanager
from json import loads
from logging import Logger
from os import getenv
from typing import Any, Literal
from uuid import uuid4

import numpy as np
from auth import create_auth_enabled_static_files
from chain import build_chains
from data_models import (
    AnswerInput,
    AnswerResult,
    ContentFilterError,
    DLFContext,
    EnhancedQuery,
    FeedbackConfig,
    FrontendConfig,
    HealthCheckResponse,
    KeywordNotFoundError,
    MailtoTemplate,
    NoAnswerFoundError,
    RetrievalDocument,
    RetrievalDocumentFull,
    RetrievalDocumentMinimal,
    RetrievalInput,
    RetrievalResult,
    ScoreInput,
)
from envtools import getenv_with_exception
from errors import (
    AnswerChainException,
    ContentFilterException,
    NoAnswerFoundException,
)
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from langchain_core.callbacks import Callbacks
from langchain_core.documents import Document
from langchain_core.runnables import RunnableConfig
from langfuse import observe, propagate_attributes
from langfuse.langchain import CallbackHandler
from logtools import getLogger
from observer import setup_langfuse
from openai import BadRequestError, OpenAIError
from qdrant_client import QdrantClient
from rerank import Reranker
from starlette.middleware.sessions import SessionMiddleware
from version import get_version

logger: Logger = getLogger()

# Popularity/visits soft-boost configuration
POPULARITY_ENABLED: bool = os.getenv("POPULARITY_ENABLED", "FALSE").upper() == "TRUE"
POPULARITY_PAYLOAD_FIELD: str = os.getenv("POPULARITY_PAYLOAD_FIELD", "unique_visits")
POPULARITY_BOOST_WEIGHT: float = float(getenv("RERANKER_SCORE_BOOST_WEIGHT", 0.2))
POPULARITY_REFRESH_SECONDS: int = int(os.getenv("POPULARITY_REFRESH_SECONDS", "86400"))

# Qdrant config (read-only is fine)
QDRANT_URL: str = os.getenv("QDRANT_URL", "http://localhost:6333").strip()
QDRANT_READONLY_API_KEY: str | None = os.getenv("QDRANT_READONLY_API_KEY") or None
VDB_COLLECTIONS: str = os.getenv("VDB_COLLECTIONS", "service")

# Rerankning overrides
RERANK_OVERRIDE: bool = (
    os.getenv("RERANK_OVERRIDE", "false").lower() == "true"
)  # default is false, reranking is configured via the frontend. This env var can be used to force override the frontend in case of issues with the reranker, e.g. if the reranker is causing timeouts, it can be disabled via this env var as a fallback.
RERANK: bool = (
    os.getenv("RERANK", "true").lower() == "true"
)  # default is true, set to false to disable reranking entirely (e.g. if the reranker is causing timeouts or errors, this can be used as a quick fallback)
# Version
VERSION = get_version()


# Content filter strings to match against
CONTENT_FILTER_STRINGS: list[str] = ["ContentPolicyViolationError", "content management policy"]

# Required env vars
SESSION_SECRET = getenv_with_exception("DLF_SESSION_SECRET")
LANGFUSE_PUBLIC_KEY = getenv_with_exception("LANGFUSE_PUBLIC_KEY")
LANGFUSE_SECRET_KEY = getenv_with_exception("LANGFUSE_SECRET_KEY")
LANGFUSE_HOST = getenv_with_exception("LANGFUSE_HOST")

# Optional env vars
SESSION_MAX_AGE = int(getenv("DLF_SESSION_MAX_AGE", 18000))  # 5 Stunden
ALLOWED_ORIGINS = getenv("DLF_ALLOWED_ORIGINS", "http://localhost:8080").split(",")
ENABLE_DOCS = getenv("DLF_ENABLE_DOCS", "true").lower() == "true"
FRONTEND_FEEDBACK_POSITIVE_MAIL_TO = getenv("FRONTEND_FEEDBACK_POSITIVE_MAIL_TO", "")
FRONTEND_FEEDBACK_POSITIVE_SUBJECT = getenv("FRONTEND_FEEDBACK_POSITIVE_SUBJECT", "")
FRONTEND_FEEDBACK_POSITIVE_BODY = getenv("FRONTEND_FEEDBACK_POSITIVE_BODY", "")
FRONTEND_FEEDBACK_NEGATIVE_MAIL_TO = getenv("FRONTEND_FEEDBACK_NEGATIVE_MAIL_TO", "")
FRONTEND_FEEDBACK_NEGATIVE_SUBJECT = getenv("FRONTEND_FEEDBACK_NEGATIVE_SUBJECT", "")
FRONTEND_FEEDBACK_NEGATIVE_BODY = getenv("FRONTEND_FEEDBACK_NEGATIVE_BODY", "")
FRONTEND_EXAMPLES = loads(getenv("FRONTEND_EXAMPLES", "[]"))


context = DLFContext()

# global popularity stats
_popularity_stats: dict[str, float | int] = {"mean": 0.0, "count": 0, "max": 0.0}
_popularity_task: asyncio.Task | None = None


def _qdrant() -> QdrantClient:
    return QdrantClient(
        url=QDRANT_URL, api_key=QDRANT_READONLY_API_KEY, port=None
    )  # port=None is mandatory to prevent request timed out https://github.com/qdrant/qdrant-client/issues/394#issuecomment-2659374059


def _extract_keywords(metadata: dict[str, Any]) -> None:
    if metadata.get("keywords") is not None:
        context.keywords.update(metadata.get("keywords"))  # type: ignore


def _extract_categories(metadata: dict[str, Any]) -> None:
    if metadata.get("categories") is not None:
        context.categories.update(metadata.get("categories").get("category_list", []))  # type: ignore


def _compute_popularity_stats_sync() -> dict[str, float | int]:
    """Scan Qdrant to compute global mean/std/max for POPULARITY_PAYLOAD_FIELD."""

    client = _qdrant()

    mean = 0.0
    m2 = 0.0
    count = 0
    max_v = 0.0
    zero_count = 0

    offset = None
    limit = 10_000

    collections = set(list(getenv("VDB_COLLECTIONS", "service,info").split(",")))
    for collection in collections:
        logger.info(f"Computing popularity stats from collection '{collection}'")
        while True:
            points, offset = client.scroll(
                collection_name=collection,
                with_payload=True,
                with_vectors=False,
                limit=limit,
                offset=offset,
                scroll_filter=None,
            )
            if not points:
                break

            for p in points:
                payload: dict[str, Any] = p.payload or {}
                v = payload.get("metadata", {}).get("site_stats", {}).get(POPULARITY_PAYLOAD_FIELD, 0.0)

                # Extract keywords and categories from metadata for frontend keyword/category list
                _extract_keywords(payload.get("metadata", {}))
                _extract_categories(payload.get("metadata", {}))
                try:
                    v = float(v)
                except Exception:
                    v = 0.0

                if not np.isfinite(v) or v < 0.0:
                    v = 0.0
                if v == 0.0:
                    zero_count += 1

                # Welford online mean/variance https://en.wikipedia.org/wiki/Algorithms_for_calculating_variance
                # update step
                count += 1
                delta = v - mean
                mean += delta / count
                m2 += delta * (v - mean)  # v - (new) mean

                if v > max_v:
                    max_v = v

            if offset is None:
                break

    # standard deviation
    std = (m2 / count) ** 0.5 if count > 1 else 0.0

    return {
        "mean": mean if count else 0.0,
        "std": std,
        "max": max_v,
        "count": count,
        "zeros": zero_count,
    }


async def _refresh_popularity_stats_periodically() -> None:
    global _popularity_stats
    while True:
        try:
            stats = await asyncio.to_thread(_compute_popularity_stats_sync)
            _popularity_stats = stats
            logger.info(
                f"Popularity stats refreshed: count={stats['count']:.0f}, mean={stats['mean']:.3f}, std={stats['std']:.3f}, max={stats['max']:.3f}"
            )
        except Exception as e:
            logger.warning(f"Failed to refresh popularity stats: {e}", exc_info=True)
        await asyncio.sleep(max(60, POPULARITY_REFRESH_SECONDS))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Set up the lifecycle of the application.

    Initializes the context and flushes the remaining traces to langfuse after shutdown.
    """
    # Setup langfuse
    langfuse, answer_prompt_template, query_prompt_template, prompt_temperature = setup_langfuse(VERSION=VERSION)
    context.langfuse = langfuse
    context.langfuse_handler = CallbackHandler()
    logger.info(f"Proxies: {os.getenv('HTTP_PROXY')}, {os.getenv('HTTPS_PROXY')}, {os.getenv('NO_PROXY')}")
    # Setup reranker
    context.reranker = Reranker()

    # Build chains and mount the routes
    context.vectorstore, context.retriever, context.answer_chain = build_chains(
        answer_prompt_template=answer_prompt_template,
        query_prompt_template=query_prompt_template,
        prompt_temperature=prompt_temperature,
        reranker=context.reranker,
        stats_provider=lambda: _popularity_stats,
    )

    # start popularity refresher
    global _popularity_task
    if POPULARITY_ENABLED:
        _popularity_task = asyncio.create_task(_refresh_popularity_stats_periodically())

    if os.getenv("LOAD_KEYWORDS_FROM_FILE", "false").lower() == "true":
        if os.path.exists(os.getenv("KEYWORDS_FILE_PATH", "keywords.txt")):
            with open(os.getenv("KEYWORDS_FILE_PATH", "keywords.txt"), "r", encoding="utf-8") as f:
                for kw in f.readlines():
                    context.keywords.add(kw.strip())
    if os.getenv("LOAD_CATEGORIES_FROM_FILE", "false").lower() == "true":
        if os.path.exists(os.getenv("CATEGORIES_FILE_PATH", "categories.txt")):
            with open(os.getenv("CATEGORIES_FILE_PATH", "categories.txt"), "r", encoding="utf-8") as f:
                for cat in f.readlines():
                    context.categories.add(cat.strip())

    yield
    # called after shutdown
    if _popularity_task:
        _popularity_task.cancel()
        try:
            await _popularity_task
        except asyncio.CancelledError:
            pass  # this is expected if ctrl + c

    if LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY and LANGFUSE_HOST:
        assert context.langfuse is not None, "Langfuse must be initialized before flushing."

        context.langfuse.flush()  # flush all remaining trace score annotations


def _get_session_id(request: Request) -> str:
    """Extracts the session id from the request

    Args:
        request (Request): the request

    Returns:
        str: either an existing session_id or creates a new one
    """

    if "id" not in request.session:
        session_id = str(uuid4())
        request.session["id"] = session_id
    else:
        session_id = request.session["id"]
    return session_id


def _build_retrieval_response(
    docs: list[Document], enhanced_query: EnhancedQuery | str, result: str, easy_language: bool = False
) -> tuple[list[RetrievalDocument], EnhancedQuery | str]:
    documents = []
    for doc in docs:
        if doc.metadata.get("easy_language", False) and not easy_language:
            continue  # skip documents in easy language if not requested
        if result == "full":
            documents.append(
                RetrievalDocumentFull(
                    name=str(doc.metadata["name"]),
                    id=doc.metadata["_id"],
                    collection=doc.metadata["_collection_name"],
                    page_content=doc.page_content,
                    metadata=doc.metadata,
                )
            )
        else:
            # default is minimal
            documents.append(
                RetrievalDocumentMinimal(
                    id=doc.metadata["_id"],
                    url=doc.metadata.get("source", ""),
                    collection=doc.metadata["_collection_name"],
                    name=doc.metadata["name"],
                )
            )
    return documents, enhanced_query


# helper method for extracting session id from request and create a run_config from it
def _build_config(session_id: str, langfuse_handler: Callbacks | None, **kwargs) -> tuple[RunnableConfig, dict[str, Any]]:
    config = RunnableConfig(
        callbacks=[langfuse_handler],  # type: ignore
        metadata={"langfuse_session_id": session_id},
    )
    kwargs = kwargs
    if os.getenv("USE_LITE_LLM_CACHE", "false").lower() == "true":
        ttl = int(os.getenv("CACHE_TTL_DAYS", "1")) * 24 * 3600  # ttl days to seconds
        kwargs["extra_body"] = {"cache": {"use-cache": True, "ttl": ttl}}
    return config, kwargs


# wrapper for the retrieval chain for observability
@observe(name="DLF", as_type="span")
async def retrieval_observer(
    query: str,
    enhance_query: bool,
    keywords: list[str] | None,
    categories: list[str] | None,
    session_id: str,
    result: str = "minimal",
    collections: Literal["all"] | list[Literal["service", "info"]] = "all",
    category_match: Literal["any", "all"] = "any",
    rerank: bool = False,
    easy_language: bool = False,
    **kwargs,
) -> tuple[list[RetrievalDocument], EnhancedQuery | str]:
    assert context.retriever is not None, "Retriever must be initialized before retrieval."
    assert context.langfuse is not None, "Langfuse must be initialized before retrieval."
    assert context.langfuse_handler is not None, "Langchain handler must be initialized before retrieval."

    config, kwargs = _build_config(session_id=session_id, langfuse_handler=context.langfuse_handler, **kwargs)  # type: ignore
    retriever_input: dict[str, Any] = {
        "query": query,
        "enhance_query": enhance_query,
        "collections": collections,
        "category_match": category_match,
        "rerank": rerank,
        "kwargs": kwargs,
    }
    if keywords:
        retriever_input["keywords"] = keywords
    if categories:
        retriever_input["categories"] = categories

    docs: list[Document] = []
    enhanced_query: EnhancedQuery | str

    with propagate_attributes(
        session_id=session_id,
    ):
        docs, enhanced_query = await context.retriever.ainvoke(input=retriever_input, config=config)  # type: ignore

    return _build_retrieval_response(docs, enhanced_query, result, easy_language=easy_language)


# wrapper for answer chain for observability
@observe(name="DLF", as_type="span")
async def answer_observer(input: AnswerInput, session_id: str, **kwargs) -> AnswerResult:
    assert context.vectorstore is not None, "Vectorstore must be initialized before answering."
    assert context.langfuse is not None, "Langfuse must be initialized before answering."
    assert context.langfuse_handler is not None, "Langchain handler must be initialized before answering."
    assert context.answer_chain is not None, "Answer chain must be initialized before answering."

    config, kwargs = _build_config(session_id=session_id, langfuse_handler=context.langfuse_handler)  # type: ignore
    doc_id = input.doc.get("id", "")
    collection = input.doc.get("collection", "")
    docs = context.vectorstore[collection].get_by_ids([doc_id])
    if not docs:
        raise NoAnswerFoundException(document=doc_id)
    doc: Document = docs[0]

    answer_input: dict[str, Any] = {
        "question": input.enhanced_query.original_query,
        "reasoning": input.enhanced_query.reasoning,
        "improved_question": input.enhanced_query.refined_query
        if input.enhanced_query.refined_query != input.enhanced_query.original_query
        else "question cannot be improved",
        "language": input.enhanced_query.language_code,
        "document": doc,
        "kwargs": kwargs,
    }

    with propagate_attributes(
        session_id=session_id,
        metadata=answer_input,
    ):
        a = await context.answer_chain.ainvoke(input=answer_input, config=config)  # type: ignore
    return a


OPENAPI_DESCRIPTION = """
DLF Backend exposes Munich service-finder search capabilities for applications
and agentic tool use.

MCP exposes only explicitly configured endpoints; initially only retrieval.
Call `retrieve_munich_service_documents` with a self-contained question.

For a generic chatbot, expose the retrieval tool and request `result='full'`
when the model should generate its own answer from returned document content.
Use `result='minimal'` when the client only needs search result titles and
document ids plus source URLs, for example to display a result list, let a user
select a document, cite a source, or pass a compact reference to another
backend flow.

The answer endpoint is an optional use-case-specific helper for the bundled
frontend flow. It is not required for MCP search usage.
"""

OPENAPI_TAGS_METADATA = [
    {
        "name": "mcp",
        "description": "Endpoints intended for MCP tool exposure through the generated OpenAPI schema.",
    },
    {
        "name": "frontend",
        "description": "Endpoints primarily used by the web component frontend.",
    },
    {
        "name": "ops",
        "description": "Operational endpoints for health and backend diagnostics.",
    },
]


# FastAPI backend creation
backend = FastAPI(
    title="DLF Backend",
    description=OPENAPI_DESCRIPTION,
    version=VERSION,
    docs_url="/docs" if ENABLE_DOCS else None,
    redoc_url="/redoc" if ENABLE_DOCS else None,
    openapi_url="/openapi.json" if ENABLE_DOCS else None,
    openapi_tags=OPENAPI_TAGS_METADATA,
    lifespan=lifespan,
)

# Middleware setup
backend.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET, max_age=SESSION_MAX_AGE)
backend.add_middleware(CORSMiddleware, allow_origins=ALLOWED_ORIGINS, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


# Health check endpoint
@backend.get(
    "/api/healthz",
    tags=["ops"],
    summary="Check backend health",
    description="Returns a lightweight health and version response. Use this to verify that the backend is reachable before calling MCP-facing tools.",
    operation_id="check_backend_health",
)
def healthz() -> HealthCheckResponse:
    """
    Endpoint for checking the health status of the backend.

    Returns:
        HealthCheckResponse: The health check response including the version and status.
    """
    return HealthCheckResponse(version=VERSION)


@backend.get(
    "/api/keywords",
    tags=["mcp", "frontend"],
    summary="List available keyword filters",
    description=(
        "Returns the sorted list of metadata keywords currently available in the indexed Munich service documents. "
        "Use these exact strings in `retrieve_munich_service_documents.keywords`; unknown keywords are rejected."
    ),
    operation_id="get_available_keywords",
)
def list_keywords() -> list[str]:
    """Return the list of available metadata keywords for suggestions."""
    try:
        return sorted(list(context.keywords))
    except Exception as e:
        logger.warning(f"Failed to list keywords: {e}")
        return []


@backend.get(
    "/api/categories",
    tags=["mcp", "frontend"],
    summary="List available category filters",
    description=(
        "Returns the sorted list of document categories currently available in the indexed Munich service documents. "
        "Use these exact strings in `retrieve_munich_service_documents.categories`; unknown categories are rejected."
    ),
    operation_id="get_available_categories",
)
def list_categories() -> list[str]:
    """Return the list of available document categories."""
    try:
        return sorted(list(context.categories))
    except Exception as e:
        logger.warning(f"Failed to list categories: {e}")
        return []


@backend.get(
    "/api/config",
    response_model_exclude_none=True,
    tags=["frontend"],
    summary="Get frontend runtime configuration",
    description=("Returns UI configuration such as example prompts and feedback mail templates."),
    operation_id="get_frontend_config",
)
def config() -> FrontendConfig:
    """
    Endpoint for getting the frontend configuration.
    """
    missing = [
        name
        for name, val in [
            ("FRONTEND_FEEDBACK_POSITIVE_MAIL_TO", FRONTEND_FEEDBACK_POSITIVE_MAIL_TO),
            ("FRONTEND_FEEDBACK_POSITIVE_SUBJECT", FRONTEND_FEEDBACK_POSITIVE_SUBJECT),
            ("FRONTEND_FEEDBACK_POSITIVE_BODY", FRONTEND_FEEDBACK_POSITIVE_BODY),
            ("FRONTEND_FEEDBACK_NEGATIVE_MAIL_TO", FRONTEND_FEEDBACK_NEGATIVE_MAIL_TO),
            ("FRONTEND_FEEDBACK_NEGATIVE_SUBJECT", FRONTEND_FEEDBACK_NEGATIVE_SUBJECT),
            ("FRONTEND_FEEDBACK_NEGATIVE_BODY", FRONTEND_FEEDBACK_NEGATIVE_BODY),
        ]
        if val is None
    ]
    if missing:
        raise HTTPException(status_code=500, detail=f"Missing required environment variables: {', '.join(missing)}")

    return FrontendConfig(
        feedback=FeedbackConfig(
            positive=MailtoTemplate(
                to=FRONTEND_FEEDBACK_POSITIVE_MAIL_TO,
                subject=FRONTEND_FEEDBACK_POSITIVE_SUBJECT,
                body=FRONTEND_FEEDBACK_POSITIVE_BODY,
            ),
            negative=MailtoTemplate(
                to=FRONTEND_FEEDBACK_NEGATIVE_MAIL_TO,
                subject=FRONTEND_FEEDBACK_NEGATIVE_SUBJECT,
                body=FRONTEND_FEEDBACK_NEGATIVE_BODY,
            ),
        ),
        examples=FRONTEND_EXAMPLES,
    )  # type: ignore


# Retrieval chain route
@backend.post(
    path="/api/retrieval",
    tags=["mcp", "frontend"],
    summary="Retrieve relevant information about Munich city services",
    description=(
        "Search official City of Munich information about municipal services, eligibility, administrative procedures, "
        "required documents, fees, deadlines, forms, and responsible offices. This is a read-only search: "
        "it does not submit applications or book appointments. "
        "Provide a self-contained natural-language question, resolving references from the conversation and including "
        "relevant circumstances without unnecessary personal identifiers. "
        "Explicitly set `result='full'` to receive document text for answering; the API default `minimal` only returns "
        "document references and metadata. Leave `enhance_query=true` and `collections='all'` for general searches. "
        "Omit keywords and categories unless you already know valid exact filter values; do not invent filters. "
        "Use returned document content as evidence and cite the corresponding source URLs. "
        "The `enhanced_query` describes the search interpretation, not an authoritative answer. "
        "If results are empty or do not support the requested detail, say so and reformulate the search or ask for clarification. "
        "Omit `run_id` for a new search; the response supplies one for subsequent feedback correlation."
    ),
    operation_id="retrieve_munich_service_documents",
    responses={
        422: {"model": KeywordNotFoundError, "description": "A supplied keyword or category filter is unknown."},
    },
)
async def retrieval(input: RetrievalInput, request: Request) -> RetrievalResult:
    """Find documents that may answer a Munich service question."""
    session_id = _get_session_id(request)
    if input.run_id is None:  # Create a trace identifier for a new search.
        input.run_id = uuid4()

    # check if keyword exists
    for keyword in input.keywords or []:
        if keyword not in context.keywords:
            logger.error(f"Keyword not found: {keyword}")
            raise HTTPException(status_code=422, detail=f"Keyword not found: {keyword}")

    # check if category exists
    for category in input.categories or []:
        if category not in context.categories:
            logger.error(f"Category not found: {category}")
            raise HTTPException(status_code=422, detail=f"Category not found: {category}")

    if RERANK_OVERRIDE:
        input.rerank = RERANK

    retrieval_documents: list[RetrievalDocument]
    query: EnhancedQuery | str
    retrieval_documents, query = await retrieval_observer(
        query=input.query,
        enhance_query=input.enhance_query,
        keywords=input.keywords,
        categories=input.categories,
        session_id=session_id,
        result=input.result,
        collections=input.collections,
        category_match=input.category_match,
        rerank=input.rerank,
        easy_language=input.easy_language,
        # kwargs:
        n_results=input.n_results,
        langfuse_trace_id=input.run_id.hex,
    )

    if isinstance(query, EnhancedQuery):
        return RetrievalResult(retrieval_documents=retrieval_documents, run_id=input.run_id, enhanced_query=query)  # type: ignore
    return RetrievalResult(
        retrieval_documents=retrieval_documents,  # type: ignore
        run_id=input.run_id,
        enhanced_query=EnhancedQuery(
            reasoning="No query enhancement applied",
            search_query=query,
            refined_query=query,
            original_query=query,
            categories=[],
            language_code="de",
            was_enhanced=False,
        ),
    )


# Answer chain route
@backend.post(
    "/api/answer",
    tags=["frontend"],
    summary="Answer from one retrieved Munich service document",
    description=(
        "Optional use-case-specific helper that generates a grounded answer for a user question using exactly one retrieved document. "
        "Use a `doc` object returned by `retrieve_munich_service_documents` and pass the same `enhanced_query` and `run_id`. "
        "The response contains the source URL, a supporting quote when available, and an LLM-generated answer. "
        "Generic MCP chatbots usually do not need this endpoint; they can call retrieval with `result='full'` and generate the final answer from the returned content. "
        "If the selected document does not explicitly contain the answer, `answer_text` and `ai_response` may be null."
    ),
    operation_id="answer_from_munich_service_document",
    responses={
        404: {"model": NoAnswerFoundError, "description": "The selected document could not be found or did not produce an answer."},
        422: {"model": ContentFilterError, "description": "The question was blocked by the model provider content filter."},
    },
)
async def answer(input: AnswerInput, request: Request) -> AnswerResult:
    """Generate a grounded answer from one retrieved document."""
    session_id: str = _get_session_id(request)
    result: AnswerResult
    try:
        start = time.time()
        result: AnswerResult = await answer_observer(
            input=input,
            session_id=session_id,
            langfuse_trace_id=input.run_id.hex,
        )
        logger.debug(f"[Answer] Answer generation time: {time.time() - start}")
    except AnswerChainException:
        raise NoAnswerFoundException(document=input.doc["id"])
    except BadRequestError as error:
        if any(content_filter_string in error.message for content_filter_string in CONTENT_FILTER_STRINGS):
            logger.warning(f"Content filter exception triggered; user query: {input.enhanced_query.original_query}")
            raise ContentFilterException()
        else:
            logger.warning("Unexpected bad request error occurred.", exc_info=True)
            raise HTTPException(status_code=400, detail="Bad Request")
    except OpenAIError:
        logger.warning("Unexpected OpenAI API error occured.", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal Server Error")
    return result


# Score route. Scores the run with the given value
@backend.post(
    "/api/score",
    tags=["frontend"],
    summary="Record user feedback for a run",
    description=(
        "Stores binary user feedback in Langfuse for the current session. "
        "This endpoint is normally called by the frontend after a user rates the generated answer."
    ),
    operation_id="record_user_feedback",
)
async def score(input: ScoreInput, request: Request) -> None:
    """Scores the user feedback."""
    assert context.langfuse is not None, "Langfuse must be initialized before scoring."
    session_id = _get_session_id(request)
    context.langfuse.create_score(
        session_id=session_id,
        name="USER_FEEDBACK",
        value=float(input.value),  # required
        data_type="NUMERIC",  # optional, possibly inferred
    )


@backend.get(
    "/api/popularity-stats",
    tags=["ops"],
    summary="Get retrieval popularity boost statistics",
    description="Returns the current popularity-boost configuration and aggregate statistics used by retrieval reranking diagnostics.",
    operation_id="get_popularity_stats",
)
def popularity_stats() -> dict:
    return {
        "enabled": POPULARITY_ENABLED,
        "field": POPULARITY_PAYLOAD_FIELD,
        "boost_weight": POPULARITY_BOOST_WEIGHT,
        "stats": _popularity_stats,
    }


# Static files setup with optional basic authentication
staticFiles: StaticFiles = create_auth_enabled_static_files(directory="static", html=True)  # type: ignore
backend.mount(path="/", app=staticFiles, name="static")
