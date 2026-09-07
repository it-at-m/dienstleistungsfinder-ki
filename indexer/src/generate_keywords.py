"""
Classifies municipal (city-service) articles into up to N high-level categories.

Builds a LangChain + OpenAI chat pipeline with structured output,
and provides a function to return category suggestions with optional language and allowed-category constraints.
Model and temperature are configurable.
"""

import os

from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from qdrant_client import QdrantClient

from src.data_models import KeywordResult
from src.logtools import getLogger

logger = getLogger()


KEYWORD_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "You extract concise, high-signal KEYWORDS for municipal (city-service) articles. "
            "Produce at least 3 and at most {n} keywords. "
            "Keywords should capture the article's core topics, actions, or target audiences in user-friendly terms. "
            "Avoid boilerplate or overly generic words (e.g., 'Info', 'Service'); prefer domain-relevant terms. "
            "Use CATEGORIES as domain hints."
            "Order keywords by relevance and coverage; aim for diversity where useful. "
            "Respond in the requested LANGUAGE.",
        ),
        (
            "user",
            "TITLE: {title}\n"
            "DESCRIPTION: {description}\n"
            "LANGUAGE: {language}\n"
            "CATEGORIES: {allowed_categories}\n"
            "MAX_KEYWORDS: {n}\n",
        ),
    ]
)


def make_keyword_chain(
    model_name: str,
    temperature: float = 0.2,
):
    llm = ChatOpenAI(model=model_name, temperature=temperature).with_structured_output(KeywordResult)
    return KEYWORD_PROMPT | llm


def generate_article_keywords(
    model_name: str,
    title: str,
    description: str,
    n: int = 5,
    language: str = "de",
    allowed_categories: list[str] | None = None,
    temperature: float = 0.2,
) -> KeywordResult:
    """
    Returns up to n keywords for an article.
    If allowed_categories is provided, output is restricted to that list.
    """
    chain = make_keyword_chain(model_name=model_name, temperature=temperature)
    allowed_str = ", ".join(allowed_categories) if allowed_categories else "any"
    if n < 3:
        n = 3
    try:
        result: KeywordResult = chain.invoke(
            {
                "title": title.strip(),
                "description": (description or "").strip(),
                "language": language,
                "allowed_categories": allowed_str,
                "n": n,
            }
        )  # type: ignore
    except Exception as e:
        logger.error(f"Error occurred while classifying article categories: {e}")
        result = KeywordResult(keywords=[])
    return result


def extract_keyword_mapping_from_collection(collection: str) -> dict[str, list[str]] | None:
    """Extracts keywords for articles in the specified collection by their IDs."""

    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")

    logger.info(f"Connecting to Qdrant at {qdrant_url} to extract keywords from collection '{collection}'")
    qdrant_client = QdrantClient(url=qdrant_url, api_key=qdrant_api_key, port=None)

    collections = qdrant_client.get_collections()
    collections = [c.name for c in collections.collections]
    if collection not in collections:
        logger.error(f"Collection '{collection}' does not exist in Qdrant.")
        logger.info(f"Available collections: {collections}")
        return None

    keyword_mapping: dict[str, list[str]] = {}
    offset = None
    _limit = 10_000
    while True:
        points, offset = qdrant_client.scroll(
            collection_name=collection,
            with_payload=True,
            with_vectors=False,
            limit=_limit,
            offset=offset,
            scroll_filter=None,
        )
        if not points:
            break

        for point in points:
            payload = point.payload or {}
            doc_id: int = payload["metadata"].get("id")
            if not doc_id:
                print(f"Skipping point {point.id} without doc_id")
                continue
            keywords = payload["metadata"].get("keywords", [])
            keyword_mapping[str(doc_id)] = keywords
        if offset is None:
            break
    if keyword_mapping:
        logger.info(f"Extracted keywords for {len(keyword_mapping)} articles from collection '{collection}'")
        logger.debug(f"Sample keywords: {list(keyword_mapping.items())[:5]}")
    return keyword_mapping
