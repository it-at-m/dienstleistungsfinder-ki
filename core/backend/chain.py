import warnings
from collections.abc import Callable
from logging import Logger
from operator import itemgetter
from os import getenv
from typing import Any

from data_models import AnswerChainInput, AnswerResult, ContextAnswer, EnhancedQuery
from envtools import getenv_with_exception
from errors import NoAnswerFoundException, QuestionNotAnswerableException, QuoteNotFoundException
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda, RunnableParallel
from langchain_core.vectorstores import VectorStore, VectorStoreRetriever
from langchain_openai import OpenAIEmbeddings
from langchain_openai.chat_models import ChatOpenAI
from langchain_qdrant import FastEmbedSparse, QdrantVectorStore, RetrievalMode
from logtools import getLogger
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Fusion, FusionQuery, MatchAny
from qdrant_client.models import Filter as QFilter
from quote import process_quote
from rerank import Reranker

logger: Logger = getLogger()
NO_ANSWER_LLM_RESPONSE = "<ERR:NO_ANSWER>"


def _interleave_document_lists(
    doc_lists: list[list[Document]],
) -> list[Document]:
    """Interleave multiple ranked document lists while preserving per-list order.

    Example:
        [[a1, a2], [b1, b2, b3]] -> [a1, b1, a2, b2, b3]
    """
    merged: list[Document] = []
    max_len = max((len(docs) for docs in doc_lists), default=0)

    for i in range(max_len):
        for docs in doc_lists:
            if i < len(docs):
                merged.append(docs[i])

    return merged


def _get_doc_metadata(doc: Document) -> dict:
    """Converts a Document object to a dictionary containing the metadata.

    Args:
        doc (Document): The Document object to convert.

    Returns:
        dict: A dictionary containing the metadata of the Document.
    """
    return {
        "base_name": doc.metadata["name"],
        "url": doc.metadata["source"],
        "content": doc.page_content,
        "online_services": doc.metadata.get("online_services", []),
    }


def _get_doc_page_content(doc: Document) -> str:
    """Extracts the page content from a Document object.

    Args:
        doc (Document): The Document object to extract the page content from.

    Returns:
        str: The page content of the Document.
    """
    return doc.page_content


def _build_chat_model(temperature: float | None = None) -> ChatOpenAI:
    """
    Builds and returns an instance of the BaseChatModel.

    Args:
        temperature (Optional[float]): The temperature for the language model. If not provided the temperature specified in the environment will be used

    Returns:
        ChatOpenAI: An instance of ChatOpenAI.

    Corresponding Environment Variables:
        OPENAI_CHAT_MODEL: The LLM that is deployed, e.g gpt-4.1-mini.
        OPENAI_API_KEY: The API key for the OpenAI API.
        OPENAI_API_BASE: Base URL of the LiteLLM Proxy
        OPENAI_API_VERSION: Version of the openAI API (e.g. 2024-08-01-preview or later for structured output support)
        LLM_TEMPERATURE: The temperature for the LLM.
        LLM_TIMEOUT: The timeout for the LLM.
        LLM_MAX_RETRIES: The maximum number of retries for calling the LLM before an error is thrown.
    """
    TEMPERATURE: float = temperature if temperature else float(getenv("LLM_TEMPERATURE", 0.0))
    MODEL: str | None = getenv("OPENAI_CHAT_MODEL")
    TIMEOUT: int = int(getenv("LLM_TIMEOUT", 10))
    MAX_RETRIES: int = int(getenv("LLM_MAX_RETRIES", 2))

    if MODEL is None:
        MODEL = "gpt-4.1-mini"  # Default to a reasonable model if not set
        logger.warning("OPENAI_CHAT_MODEL not set, defaulting to gpt-4.1-mini.")

    return ChatOpenAI(model=MODEL, temperature=TEMPERATURE, timeout=TIMEOUT, max_retries=MAX_RETRIES)


def _build_embedding_model() -> Embeddings:
    """Builds and returns an instance of the AzureOpenAIEmbeddings model for OpenAI text embedding.

    Returns:
        embedding_model (Embeddings): An instance of the OpenAIEmbeddings model.

    Corresponding Environment Variables:
        OPENAI_EMBEDDING_MODEL: The model to use for the OpenAI API.
        OPENAI_API_KEY: The API key for the OpenAI API.
        OPENAI_API_BASE: Base URL of the LiteLLM Proxy
        EMB_MAX_RETRIES: The maximum number of retries for the OpenAI API.
        EMB_TIMEOUT: The timeout for the OpenAI API.
    """
    MODEL: str | None = getenv("OPENAI_EMBEDDING_MODEL")
    TIMEOUT: int = int(getenv("EMB_TIMEOUT", 10))
    MAX_RETRIES: int = int(getenv("EMB_MAX_RETRIES", 2))

    if MODEL is None:
        MODEL = "text-embedding-3-large"
        logger.warning("OPENAI_EMBEDDING_MODEL not set, defaulting to text-embedding-3-large.")

    try:
        embedding_model = OpenAIEmbeddings(
            model=MODEL,
            timeout=TIMEOUT,
            max_retries=MAX_RETRIES,
        )

        _ = embedding_model.embed_query("test")
    except Exception as e:
        logger.error(f"Failed to create embedding model with error: {e}. Exiting load script.")
        raise e
    return embedding_model


def _build_sparse_embedding_model() -> FastEmbedSparse:
    """Builds two BM25 embedding models in german and english language for the sparse vectors.

    Returns:
        FastEmbedSparse: The built sparse embedding model.

    Corresponding Environment Variables:
        EMB_SPARSE_MODEL: The model to use for the sparse embeddings.
    """
    SPARSE_MODEL_NAME = getenv("EMB_SPARSE_MODEL", "Qdrant/bm25")
    cache_dir = getenv("FASTEMBED_CACHE_PATH", "./model_cache")
    sparse_embedding_model = FastEmbedSparse(model_name=SPARSE_MODEL_NAME, language="german", cache_dir=cache_dir)
    return sparse_embedding_model


def _build_vectorstore(embedding_model: Embeddings, sparse_embedding_model: FastEmbedSparse, collection: str = "info") -> QdrantVectorStore:
    """Builds a Qdrant vector store using the given embedding model.

    Parameters:
        embedding_model (Embeddings): The embedding model to use for building the vector store.
        dimension (int): The dimension of the embeddings.

    Returns:
        VectorStore: The built vector store.

    Corresponding Environment Variables:
        QDRANT_API_KEY: The API key for the Qdrant API.
        QDRANT_URL: The URL for the Qdrant Instance.
        VDB_COLLECTION_NAME: The name of the collection to use for the vector store.
        VDB_DENSE_VECTOR_NAME: The name of the dense vector in the collection.
        VDB_SPARSE_VECTOR_NAME: The name of the sparse vector in the collection.
        VDB_TIMEOUT: The timeout for the Qdrant requests.
    """
    URL: str = getenv_with_exception("QDRANT_URL")
    API_KEY: str = getenv_with_exception("QDRANT_READONLY_API_KEY")
    DENSE_VECTOR_NAME: str = getenv("VDB_DENSE_VECTOR_NAME", "dense")
    SPARSE_VECTOR_NAME: str = getenv("VDB_SPARSE_VECTOR_NAME", "sparse")
    TIMEOUT: int = int(getenv("VDB_TIMEOUT", 10))
    COLLECTION_NAME: str = collection

    logger.debug("Check first if the collection exists")
    qdrant_client = QdrantClient(url=URL, api_key=API_KEY, port=None, timeout=TIMEOUT)

    if not qdrant_client.collection_exists(COLLECTION_NAME):
        logger.error(f"Collection {COLLECTION_NAME} does not exist. Can't run RAG without collection. Exiting.")
        exit(-1)

    vectorstore = QdrantVectorStore(
        client=qdrant_client,
        collection_name=COLLECTION_NAME,
        retrieval_mode=RetrievalMode.HYBRID,
        vector_name=DENSE_VECTOR_NAME,
        embedding=embedding_model,
        sparse_vector_name=SPARSE_VECTOR_NAME,
        sparse_embedding=sparse_embedding_model,
    )

    return vectorstore


def _build_retriever(vectorstore: VectorStore) -> VectorStoreRetriever:
    """Builds a retriever from a given vectorstore.

    Parameters:
        vectorstore (VectorStore): The vectorstore to build the retriever from.

    Returns:
        VectorStoreRetriever: The retriever object.

    Corresponding Environment Variables:
        VDB_RETRIEVAL_SCORE_THRESHOLD: The score threshold for the retriever.
        VDB_RETRIEVAL_N_DOCS: The number of documents to retrieve.
        VDB_RETRIEVAL_FUSION: The fusion method to use for the retriever.
    """
    N_DOCS = int(getenv("VDB_RETRIEVAL_N_DOCS", 10))
    SCORE_THRESHOLD = float(getenv("VDB_RETRIEVAL_SCORE_THRESHOLD", 0.5))
    FUSION_METHOD = getenv("VDB_RETRIEVAL_FUSION", "DBSF").lower()

    if FUSION_METHOD not in [Fusion.DBSF, Fusion.RRF]:
        logger.warning(f"Invalid method mode {FUSION_METHOD}. Using default DBSF instead.")
        FUSION_METHOD = Fusion.DBSF

    # Supress langchain UserWarning "Relevance scores must be between 0 and 1" due to hybrid embedding with score > 1
    warnings.filterwarnings("ignore", category=UserWarning)

    retriever: VectorStoreRetriever = vectorstore.as_retriever(
        search_type="similarity_score_threshold",
        search_kwargs={
            "score_threshold": SCORE_THRESHOLD,
            "k": N_DOCS,
            "hybrid_fusion": FusionQuery(fusion=Fusion(FUSION_METHOD)),
        },
    )

    return retriever


def _post_process_answer(result: dict) -> AnswerResult:
    """Wraps the output of the answer chain into a FrontendDocument object and processes the quote.

    Args:
        result (dict): The result of the answer chain.

    Returns:
        into: The answer including the processed quote.
    """
    artikel_antwort: ContextAnswer = result["answer"]
    document_name: str = result["meta"]["base_name"]
    document_url: str = result["meta"]["url"]

    if artikel_antwort.relevance_score <= 80:
        logger.debug(
            "Answer marked as not answerable (relevance_score=%r, type=%s) for doc '%s'",
            artikel_antwort.relevance_score,
            type(artikel_antwort.relevance_score).__name__,
            document_name,
        )
        raise QuestionNotAnswerableException()

    try:
        answer_quote = process_quote(artikel_antwort.quote, result["meta"]["content"])
    except QuoteNotFoundException as e:
        logger.warning(f"Quote '{e.quote}' not found in the article '{document_name}'.")
        raise NoAnswerFoundException(document=document_name)
    return AnswerResult(
        doc_base_name=document_name,
        doc_url=document_url,
        answer_text=answer_quote,
        ai_response=artikel_antwort.answer,
    )


def _load_configured_collections() -> set[str]:
    """Load configured vector store collection keys from environment."""
    return set(list(getenv("VDB_COLLECTIONS", "service,info").split(",")))


async def _retrieve_documents(
    base_retrievers: dict[str, VectorStoreRetriever], query: str, collections: str | list[str], **kwargs
) -> dict[str, list[Document]]:
    """Retrieves documents from the vector stores using the provided query and filters.

    Args:
        base_retrievers (dict[str, VectorStoreRetriever]): The base retrievers for each collection.
        query (str): The query string to search for.
        **kwargs: Additional keyword arguments for filtering.

    Returns:
        dict[str, list[Document]]: A dictionary mapping collection names to lists of retrieved documents.
    """
    docs = {}
    for collection, retriever in base_retrievers.items():
        if collections == "all":
            docs[collection] = await retriever.ainvoke(query, **kwargs)
        else:
            if collection in collections:
                docs[collection] = await retriever.ainvoke(query, **kwargs)
    return docs


def _extract_state(state: dict) -> dict:
    """Extract prompt-relevant state from an input payload.

    Args:
        state (dict): Input state containing "question" and "document".

    Returns:
        dict: Normalized prompt state with question, language, meta, and context.
    """
    doc: Document = state["document"]
    return {
        "question": state["question"],
        "reasoning": state.get("reasoning", "No reasoning over query provided"),
        "improved_question": state.get("improved_question", state["question"]),
        "language": state.get("language", "No language specified"),
        "meta": _get_doc_metadata(doc),
        "context": _get_doc_page_content(doc),
        "kwargs": state.get("kwargs", {}),
    }


def _build_prompt_input(input: dict) -> dict:
    """Build the structured prompt input for the answer chain.

    Args:
        input (dict): Extracted state with question, meta, context, and kwargs.

    Returns:
        dict: Prompt input ready for the answer model.
    """
    prompt_input = {
        "question": input["question"],
        "reasoning": input.get("reasoning", "No reasoning over query provided"),
        "improved_question": input.get("improved_question", input["question"]),
        "language": input.get("language", "No language specified"),
        "online_services": "; ".join(service for service in input["meta"].get("online_services", [])),  # ensure services is a string
        "context": input["context"],
        "kwargs": input.get("kwargs", {}),
    }
    for k, v in prompt_input.items():
        if k != "context":
            logger.debug(k + ": " + str(v))
    return prompt_input


def _merge_for_postprocess(r: dict, kwargs: dict | None = None) -> dict:
    """Merge answer/meta/context into the structure expected by postprocessing.

    Args:
        r (dict): Result dict containing "answer", "meta", and "content".
        kwargs (dict | None): Optional kwargs (unused, reserved for compatibility).

    Returns:
        dict: Dict with keys "answer" and "meta" (including "content").
    """
    # _post_process_answer expects dict with keys: answer (ContextAnswer), meta (incl. 'content')
    meta_with_content = {**r["meta"], "content": r["content"]}
    return {"answer": r["answer"], "meta": meta_with_content}


def build_chains(
    answer_prompt_template: ChatPromptTemplate,
    query_prompt_template: ChatPromptTemplate,
    prompt_temperature: float | None = None,
    reranker: Reranker | None = None,
    stats_provider: Callable[[], dict[str, float | int]] | None = None,
) -> tuple[dict[str, QdrantVectorStore], Runnable, Runnable[AnswerChainInput, AnswerResult]]:
    """Builds and returns a retrieval chain for the DLF RAG app.

    Args:
        prompt_template (ChatPromptTemplate): The template for generating prompts for the chat model.
        prompt_temp (Optional[float]): The temperature value for generating prompts. Defaults to None.

    Returns:
        tuple: The vectorstores, retrieval chain, and answer chain.

    Corresponding Environment Variables:
        SYSTEM_PROMPT: The system prompt used for the chat model.
    """
    logger.info("Building chains for DLF RAG app.")

    # Append instruction to keep quotes concise to avoid fuzzy matching issues with long quotes
    # important fix for new model (gpt-4.1-mini) that tends to output very long quotes, which break the quote matching!
    # NOTE: we do not want to modify the optimized RAG prompt managed in langfuse!
    if hasattr(answer_prompt_template, "messages") and isinstance(answer_prompt_template.messages, list):
        answer_prompt_template.messages.append(
            SystemMessage(
                content="IMPORTANT: Keep the 'quote' field concise. Select only the specific sentences/short sections that answer the question. Avoid quoting multiple paragraphs if possible."
            )
        )

    # load configured collections
    collections = _load_configured_collections()
    logger.info(f"Configured collections: {collections}")

    chat_model: ChatOpenAI = _build_chat_model(temperature=prompt_temperature)
    embedding_model: Embeddings = _build_embedding_model()
    sparse_embedding_model: FastEmbedSparse = _build_sparse_embedding_model()

    logger.info("Chat and embedding models created successfully.")
    vectorstores: dict[str, QdrantVectorStore] = {}
    base_retrievers: dict[str, VectorStoreRetriever] = {}
    for c in collections:
        vectorstores[c] = _build_vectorstore(embedding_model, sparse_embedding_model, collection=c)
        base_retrievers[c] = _build_retriever(vectorstores[c]).with_config({"run_name": f"VECTORSTORE_RETRIEVER_{c}"})  # type: ignore

    logger.info("Vectorstore and base retriever created successfully.")

    # Create structured models from the raw chat_model
    structured_chat_model: Runnable = chat_model.with_structured_output(ContextAnswer, method="json_schema")
    structured_query_model: Runnable = chat_model.with_structured_output(EnhancedQuery, method="json_schema")

    # --- Retrieval chain with query rephrasing and reranking ---
    # input expects: {"query": str}
    # steps:
    #   1. ENHANCE -> improve query with llm
    #   2. RETRIEVE -> get relevant documents from vectorstore
    #   3. RERANK -> re-rank documents with re-ranker

    # Kept inside build_chains for convenience:
    #   it closes over the freshly built vectorstore/retriever/reranker without extra parameters or a wrapper class,
    #   and keeps implementation details local
    query_enhancer: Runnable = (query_prompt_template | structured_query_model).with_config({"run_name": "QUERY_ENHANCER"})

    async def _rewrite_query(inputs: dict) -> dict:
        """Rewrite the query using the LLM if enabled.

        Args:
            inputs (dict): Input state containing "query" and "enhance_query".

        Returns:
            dict: Updated input state containing "enhanced_query".
        """
        logger.debug(f"Rewriting query with inputs: {inputs}")
        kwargs = inputs.get("kwargs", {})
        if inputs.get("enhance_query"):
            rewritten_query: EnhancedQuery = await query_enhancer.ainvoke(inputs["query"], **kwargs)
            logger.info(
                f"Original query: '{inputs['query']}' | Rewritten query: '{rewritten_query.search_query}' | Was enhanced: {rewritten_query.was_enhanced}"
            )
        else:
            rewritten_query: EnhancedQuery = EnhancedQuery(
                reasoning="Query enhancement skipped as per input flag. Using original query.",
                search_query=inputs["query"],
                refined_query=inputs["query"],
                original_query=inputs["query"],
                was_enhanced=False,
                categories=[""],
                language_code="de",
            )
        inputs["enhanced_query"] = rewritten_query
        return inputs

    async def _retrieve(inputs) -> dict[str, list[Document] | dict]:
        """Retrieve documents, optionally filtering by metadata keywords via Qdrant payload filter.

        Args:
            inputs (dict): Dict with keys "query", "keywords", "categories", and "collections".

        Returns:
            dict[str, list[Document] | dict]: Retrieved docs per collection and kwargs passthrough.
        """
        logger.debug(f"Retrieving documents with inputs: {inputs}")
        # query: str = inputs.get("enhanced_query").query if inputs.get("enhanced_query") else inputs.get("query")
        query: str = inputs.get("enhanced_query").search_query if inputs.get("enhanced_query") else inputs.get("query")
        logger.info(f"Using query for retrieval: '{query}'")
        keywords: list[str] | None = inputs.get("keywords")
        categories: list[str] | None = inputs.get("categories")
        collections: list[str] = inputs.get("collections")

        filter_conditions: list[Any] = []
        if keywords is not None and len(keywords) > 0:
            filter_conditions.append(FieldCondition(key="metadata.keywords", match=MatchAny(any=keywords)))
        if categories is not None and len(categories) > 0:
            filter_conditions.append(FieldCondition(key="metadata.categories.category_list", match=MatchAny(any=categories)))

        # If any filter conditions exist, attempt filtered retrieval first.
        if len(filter_conditions) > 0:
            try:
                q_filter = QFilter(must=filter_conditions)
                search_kwargs = {"filter": q_filter}
                docs = await _retrieve_documents(base_retrievers=base_retrievers, query=query, collections=collections, **search_kwargs)
                return {"docs": docs, "kwargs": inputs.get("kwargs", {})}
            except Exception as e:
                logger.warning(f"Filtered retrieval failed, falling back to unfiltered. Error: {e}")
                # fall through to base retriever

        # Default: no filters
        docs = await _retrieve_documents(
            base_retrievers=base_retrievers,
            query=query,
            collections=collections,
        )
        logger.info("retrieved documents!")
        return {"docs": docs, "kwargs": inputs.get("kwargs", {})}

    async def _rerank(inputs) -> tuple[list[Document], EnhancedQuery | str]:
        """Rerank retrieved documents when enabled.

        Args:
            inputs (dict): Dict containing retrieval results and rerank flags.

        Returns:
            tuple[list[Document], EnhancedQuery | str]: Reranked docs and the effective query.
        """
        docs: list[Document] = []
        kwargs = inputs.get("retrieval", {}).get("kwargs", {})
        n_results: int | None = kwargs.get("n_results")
        if not inputs.get("rerank"):
            logger.info("Skipping reranking!")
            retrieval_docs: dict[str, list[Document]] = inputs.get("retrieval", {}).get("docs", {})

            # merge the docs from the different collections and interleave them to ensure a mix of results from all collections, while preserving the original order within each collection
            docs = _interleave_document_lists(list(retrieval_docs.values()))
            for doc in docs:
                logger.debug(f"Collection: {doc.metadata['_collection_name']}, Name: {doc.metadata.get('name')}")

            # limit to n_results after merging all collections to ensure we return the most relevant docs overall, not n per collection
            if n_results is not None:
                docs = docs[:n_results]

            return docs, inputs.get("enhanced_query") if inputs.get("enhanced_query") else inputs.get("query")

        if reranker is not None:
            try:
                stats: dict[str, Any] = stats_provider() if stats_provider else {}
                # query: str = inputs.get("enhanced_query").query if inputs.get("enhanced_query") else inputs.get("query")
                query: str = inputs.get("enhanced_query").refined_query if inputs.get("enhanced_query") else inputs.get("query")
                logger.info(f"Using query for reranking: '{query}'")
                kwargs = inputs.get("retrieval")["kwargs"]  # defined in _retrieve
                kwargs["n_results"] = n_results  # pass n_results to reranker to limit final output
                docs = await reranker.arerank_documents(query, inputs.get("retrieval")["docs"], stats, **kwargs)
            except Exception as e:
                logger.warning(f"Reranker failed: {e}")
        return docs, inputs.get("enhanced_query") if inputs.get("enhanced_query") else inputs.get("query")

    retriever: Runnable = (
        RunnableParallel(
            query=itemgetter("query"),
            enhanced_query=itemgetter("enhanced_query"),
            rerank=itemgetter("rerank"),
            retrieval=RunnableLambda(_retrieve).with_config({"run_name": "VECTORSTORE_RETRIEVAL"}),
        ).with_config({"run_name": "RETRIEVAL"})
        | RunnableLambda(_rerank).with_config({"run_name": "RERANKING"})  # type: ignore
    ).with_config({"run_name": "RETRIEVER"})

    rewrite_query: Runnable = RunnableLambda(_rewrite_query).with_config({"run_name": "REWRITE_QUERY"})
    retriever_chain: Runnable = (rewrite_query | retriever).with_config({"run_name": "RETRIEVER_CHAIN"})

    # --- Simplified Answer Chain (more clarity than original encapsulated chain) ---
    # Input expects: {"question": str, "document": Document}
    # Steps:
    #   1. EXTRACT -> gather meta + context + question
    #   2. PARALLEL_ANSWER -> run LLM on (question, context) while passing meta/context through
    #   3. MERGE_RESULT -> format into structure expected by post process
    #   4. POSTPROCESS -> convert to AnswerResult

    extract_step: Runnable = RunnableLambda(_extract_state).with_config({"run_name": "EXTRACT_DOC_CONTENTS"})
    build_prompt_input: Runnable = RunnableLambda(_build_prompt_input).with_config({"run_name": "BUILD_PROMPT_INPUT"})

    # generate answer with additional kwargs from input
    # neccessary for caching to work properly
    async def _answer(inputs) -> ContextAnswer:
        """Generate a structured answer for a given prompt input.

        Args:
            inputs (dict): Prompt input containing question/context and optional kwargs.

        Returns:
            ContextAnswer: The structured answer output.
        """
        kwargs = inputs.get("kwargs", {})
        prompt = await answer_prompt_template.ainvoke(inputs)
        return await structured_chat_model.ainvoke(prompt, **kwargs)

    generate_answer: Runnable = RunnableLambda(_answer).with_config({"run_name": "GENERATE_ANSWER"})

    parallel_answer: Runnable = RunnableParallel(
        {
            "answer": build_prompt_input | generate_answer,
            # keep meta + context for quote processing later
            "meta": itemgetter("meta"),
            "content": itemgetter("context"),
        }
    ).with_config({"run_name": "PARALLEL_ANSWER"})

    merge_step: Runnable = RunnableLambda(_merge_for_postprocess).with_config({"run_name": "MERGE_RESULT"})
    postprocess_step: Runnable = RunnableLambda(_post_process_answer).with_config({"run_name": "POSTPROCESS_ANSWER"})

    answer_chain: Runnable[AnswerChainInput, AnswerResult] = (
        (extract_step | parallel_answer | merge_step | postprocess_step)
        .with_types(input_type=AnswerChainInput, output_type=AnswerResult)
        .with_config({"run_name": "ANSWER_CHAIN"})
    )  # type: ignore

    # expose a consistent variable name for return signature compatibility
    postprocess_answer_chain: Runnable[AnswerChainInput, AnswerResult] = answer_chain

    logger.info("Chains created successfully.")
    return vectorstores, retriever_chain, postprocess_answer_chain
