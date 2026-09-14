from abc import ABC
from os import getenv
from typing import Any, Literal, TypedDict
from uuid import UUID

from langchain_core.documents.base import Document
from langchain_core.runnables import Runnable
from langchain_qdrant import QdrantVectorStore
from langfuse import Langfuse
from langfuse.langchain import CallbackHandler
from pydantic import BaseModel, ConfigDict, Field
from rerank import Reranker

QUERY_MAXLENGTH = int(getenv("DLF_QUERY_MAXLENGTH", 300))


class ContextAnswer(BaseModel):
    """
    Structured response for a user question given exactly one context document.

    Contract (threshold-gated):
    - relevance_score is ALWAYS set (0..100).
    - quote and answer are ONLY provided when the document explicitly and directly supports a complete answer.
      Otherwise they MUST be None.
    """

    quote: str | None = Field(
        default=None,
        description=(
            "A direct, word-for-word excerpt from the provided context that best supports the answer. "
            "MUST be an exact substring of the context (no paraphrasing). "
        ),
    )

    answer: str | None = Field(
        default=None,
        description=(
            "A complete answer to the user's question derived ONLY from explicit statements in the context, "
            "in the required output language. "
            "Must not rely on inference, assumption, interpretation, or exclusion."
        ),
    )

    relevance_score: int = Field(
        ge=0,
        le=100,
        description=(
            "Integer score from 0 to 100 measuring how strongly the context explicitly and directly supports "
            "a complete answer to the question. "
        ),
    )


class HealthCheckResponse(BaseModel):
    """Backend reachability and version information."""

    status: str = Field(description="Backend status. `ok` means the API process is running.", default="ok")
    version: str = Field(description="Backend application version currently serving requests.", examples=["v0.1.0"])


class RetrievalInput(BaseModel):
    """Search request for finding Munich service documents relevant to a question."""

    query: str = Field(
        description=(
            "Self-contained natural-language search question including relevant context from the conversation. "
            "The backend can enhance the query for German administrative terminology when `enhance_query` is true."
        ),
        max_length=QUERY_MAXLENGTH,
        examples=["Welche finanzielle Unterstützung kann ich bei geringem Einkommen in München beantragen?"],
    )
    enhance_query: bool = Field(
        description=(
            "When true, the backend rewrites the question into search-friendly German administrative terminology. "
            "Use true for normal natural-language questions."
        ),
        default=True,
    )
    keywords: list[str] | None = Field(
        description=(
            "Optional metadata keyword filters. Use only known exact keyword values; omit this field when no keyword filter is needed."
        ),
        default=None,
    )
    categories: list[str] | None = Field(
        description=(
            "Optional document category filters. Use only known exact category values; omit this field when no category filter is needed."
        ),
        default=None,
    )
    run_id: UUID | None = Field(
        description=(
            "Optional trace identifier. If omitted, retrieval creates a new run_id. "
            "Reuse the resulting run_id for observability and feedback correlation."
        ),
        examples=[UUID("3fff1df2-e7a4-4f6c-ba98-d0529cdc22ff")],
        default=None,
    )
    result: Literal["minimal", "full"] = Field(
        description=(
            "Controls document payload size. `full` returns document content and metadata for direct use as retrieval context. "
            "`minimal` returns document id, collection, title, and source URL for compact result lists, selection, or lookup by id."
        ),
        default="minimal",
    )
    collections: Literal["all"] | list[Literal["service", "info"]] = Field(
        description=(
            "Collections to search. Use `all` for normal service-finder questions, or restrict to `service` and/or `info` when the caller knows the desired source type."
        ),
        default="all",
    )
    category_match: Literal["any", "all"] = Field(
        description="Category filter strategy. `any` returns documents matching at least one category; `all` requires every supplied category.",
        default="any",
    )
    rerank: bool = Field(
        description="When true, rerank retrieved documents for relevance before returning them. Use true when answer quality matters more than latency.",
        default=False,
    )
    easy_language: bool = Field(
        description="When true, include documents marked as easy-language content. By default those documents are excluded.",
        default=False,
    )
    n_results: int | None = Field(
        description="Maximum number of candidate documents to return. Omit to use the backend default. Allowed range is 1 to 20.",
        default=None,
        ge=1,
        le=20,
    )


class RetrievalDocument(BaseModel, ABC):
    """Common fields for a retrieved document candidate."""

    id: str = Field(
        description="Stable document id in the vector store. Use it to identify, display, or fetch this search result in downstream application flows.",
        examples=["1d6527be-ea60-5e62-af55-8c7e05658164"],
    )
    collection: str = Field(
        description="Vector-store collection containing this document. Keep it with the document id when referencing the search result.",
        examples=["service"],
    )
    name: str = Field(
        description="Human-readable document title for display and candidate selection.", examples=["Hilfe zum Lebensunterhalt"]
    )
    model_config = ConfigDict(from_attributes=True)


class RetrievalDocumentMinimal(RetrievalDocument):
    """Compact retrieved document candidate containing identifiers, title, and source URL."""

    kind: Literal["minimal"] = "minimal"
    url: str = Field(
        description="Public source URL for the retrieved document. Use this to cite or link the search result.",
        examples=["https://stadt.muenchen.de/service/info/hilfe-zum-lebensunterhalt/10387547/"],
    )


class RetrievalDocumentFull(RetrievalDocument):
    """Retrieved document candidate including raw content and metadata."""

    kind: Literal["full"] = "full"
    page_content: str = Field(
        description="Full indexed document text. Request `result='full'` when the caller needs retrieval context for answer generation.",
        examples=["Full content of the document."],
    )
    metadata: dict[str, Any] = Field(
        description="Raw metadata associated with the retrieved document, such as source URL, categories, and keywords."
    )


class EnhancedQuery(BaseModel):
    """
    Search-optimized representation of the user's question.

    This object explains how retrieval interpreted the query and can be shown,
    logged, or reused by application-specific follow-up flows.
    """

    reasoning: str = Field(description="Brief explanation of how the original question was mapped to Munich administrative terminology.")

    search_query: str = Field(
        description="Keyword-optimized German search query used internally for retrieval. It intentionally omits the city name."
    )

    refined_query: str = Field(description="Cleaned version of the user's original intent used by the answer model.")

    original_query: str = Field(description="The user query before enhancement.")

    categories: list[str] = Field(
        description="Administrative categories inferred during query enhancement.",
    )

    language_code: str = Field(description="ISO 639-1 language code detected from the user input, for example `de` or `en`.")

    was_enhanced: bool = Field(description="True when the backend modified the query or added administrative search terms.")


class RetrievalResult(BaseModel):
    """Search result containing candidate documents and query interpretation."""

    retrieval_documents: list[RetrievalDocumentMinimal | RetrievalDocumentFull] = Field(
        description=(
            "Ranked candidate documents. With `result='full'`, each item includes document content and metadata. "
            "With `result='minimal'`, each item contains document id, collection, title, and source URL."
        ),
    )
    run_id: UUID = Field(
        description="Trace identifier for this retrieval workflow. Reuse it unchanged for feedback and observability.",
        examples=[UUID("3fff1df2-e7a4-4f6c-ba98-d0529cdc22ff")],
    )
    enhanced_query: EnhancedQuery = Field(
        description="Search-optimized query context explaining how the user question was interpreted for retrieval."
    )


class AnswerInput(BaseModel):
    """Request for the optional application-specific answer helper."""

    doc: dict[str, str] = Field(
        description=(
            "Document selector from a retrieval result. Must contain `id` and `collection` exactly as returned by "
            "`retrieve_munich_service_documents`."
        ),
        examples=[{"id": "1d6527be-ea60-5e62-af55-8c7e05658164", "collection": "service"}],
    )
    enhanced_query: EnhancedQuery = Field(
        description="The `enhanced_query` object returned by `retrieve_munich_service_documents`. Pass it unchanged when using this helper.",
    )
    run_id: UUID = Field(
        description="Trace identifier returned by retrieval. Pass it unchanged for observability.",
        examples=[UUID("3fff1df2-e7a4-4f6c-ba98-d0529cdc22ff")],
    )


class AnswerChainInput(TypedDict):
    """Input for the answer chain."""

    question: str
    document: Document
    kwargs: dict[str, Any] | None


class AnswerResult(BaseModel):
    """Grounded answer generated from a single Munich service document."""

    doc_base_name: str = Field(
        description="Title of the source document used for the answer.",
        examples=["Hilfe zum Lebensunterhalt"],
    )
    doc_url: str = Field(
        description="Public URL of the source document. Use this as the citation target for the answer.",
        examples=["https://stadt.muenchen.de/service/info/hilfe-zum-lebensunterhalt/10387547/"],
    )
    answer_text: str | None = Field(
        description=(
            "Short exact quote from the source document that supports the answer. "
            "Null means this document did not explicitly support a grounded answer."
        ),
    )
    ai_response: str | None = Field(
        description=(
            "Natural-language answer derived only from the selected document. "
            "Null means the question was not answerable from this document."
        ),
        examples=[
            "Wenn Sie Unterstützung benötigen, können Sie finanzielle Hilfen beantragen, die folgende Leistungen umfassen: maßgebliche Regelleistung, angemessene Kosten für Unterkunft und Heizung, zusätzliche Mehrbedarfe (zum Beispiel für Ernährung) und einmalige Bedarfe. Für spezielle Anliegen gibt es auch besondere Anlaufstellen, wie den Sozialdienst für Gehörlose oder die Zentrale Wohnungslosenhilfe."
        ],
    )


class ScoreInput(BaseModel):
    """Binary user feedback for an observed answer workflow."""

    run_id: UUID = Field(
        description="Trace identifier for the retrieval or answer run being rated.",
        examples=[UUID("3fff1df2-e7a4-4f6c-ba98-d0529cdc22ff")],
    )
    value: bool = Field(description="User rating. True means positive feedback; false means negative feedback.")


class DLFContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    vectorstore: dict[str, QdrantVectorStore] | None = None
    retriever: Runnable[str, list[Document]] | None = None
    answer_chain: Runnable[AnswerChainInput, AnswerResult] | None = None
    langfuse: Langfuse | None = None
    langfuse_handler: CallbackHandler | None = None
    reranker: Reranker | None = None
    keywords: set[str] = set()
    categories: set[str] = set()


class MailtoTemplate(BaseModel):
    to: str = Field(description="Recipient email address for collecting frontend feedback.", examples=["feedback@example.com"])
    subject: str = Field(
        description="Subject line for the generated feedback email.",
        examples=["KI-Suche Feedback"],
    )
    body: str = Field(
        description="Body template for the generated feedback email. The frontend appends run_id and query context.",
        examples=["Hallo DLF-Team, hier mein Feedback..."],
    )


class FeedbackConfig(BaseModel):
    """Positive and negative feedback email templates for the frontend."""

    positive: MailtoTemplate
    negative: MailtoTemplate


class FrontendConfig(BaseModel):
    """Runtime configuration consumed by the search web component."""

    feedback: FeedbackConfig = Field(description="Mail templates used by the frontend feedback UI.")
    examples: list[str] = Field(description="Example questions shown by the frontend.")


class NoAnswerFoundError(BaseModel):
    detail: str = "No answer found in document '{x}'."


class ContentFilterError(BaseModel):
    detail: str = "Content filter was triggered by question."


class KeywordNotFoundError(BaseModel):
    detail: str = "Keyword not found."
