# ruff: noqa: E402 (no import at top level) suppressed on this file as we need to inject the truststore before importing the other modules

import sys
from collections.abc import Callable
from os import getenv
from uuid import NAMESPACE_URL, uuid5

from dotenv import load_dotenv
from langchain_core.documents.base import Document
from qdrant_client import QdrantClient
from truststore import inject_into_ssl

from src.collect_and_extract_info import _fetch_articles, _magnolia_article_to_doc
from src.collect_and_extract_service import collect_and_extract
from src.data_models import SearchResponse
from src.load import load
from src.logtools import getLogger
from src.site_visits import add_site_visits_main
from src.transform import transform
from src.utils import _configured_collection_keys

inject_into_ssl()
load_dotenv()


logger = getLogger()


CollectionBuilder = Callable[[], tuple[str, list[Document]]]
NAMESPACE_DLF = uuid5(NAMESPACE_URL, "https://stadt.muenchen.de/buergerservice")


def _build_service_documents() -> tuple[str, list[Document]]:
    """Collect and transform service articles into LangChain documents."""

    MIN_ARTICLES = int(getenv("DLF_INDEXER_MIN_ARTICLES", 800))
    detailed_articles = collect_and_extract()
    if not detailed_articles:
        logger.error("No detailed articles for info db found. Script aborting.")
        exit(-1)
    if getenv('SAVE_ARTICLES', False):
        with open("artifacts/articles.jsonl", mode='w', encoding="utf-8") as fp:
            print("saving articles!")
            for article in detailed_articles:
                fp.write(article.model_dump_json())
                fp.write('\n')

    if len(detailed_articles) < MIN_ARTICLES:
        logger.error(
            "Too few articles extracted: Got %d, expected at least %d. Script aborting.",
            len(detailed_articles),
            MIN_ARTICLES,
        )
        exit(-1)
    
    transformed_articles = transform(detailed_articles)
    documents = [
            Document(
                page_content=article.page_content,
                metadata=article.model_dump(exclude={"page_content"}),
                id=str(uuid5(NAMESPACE_DLF, str(article.id))),
            ) for article in transformed_articles
        ]
    return "service", documents


def _build_info_documents() -> tuple[str, list[Document]]:
    """Fetch Magnolia info articles and convert them to documents."""

    logger.info("Fetching info articles")
    api_docs: SearchResponse = _fetch_articles()

    logger.info("Fetched %d info articles", len(api_docs.results))
    logger.info("converting articles to documents")
    documents = [_magnolia_article_to_doc(article) for article in api_docs.results]
    return "info", documents


_COLLECTION_BUILDERS: dict[str, CollectionBuilder] = {
    "service": _build_service_documents,
    "info": _build_info_documents,
}


def build_collection_documents() -> dict[str, list[Document]]:
    """Run configured builders and return documents keyed by collection."""

    collections: dict[str, list[Document]] = {}

    for key in _configured_collection_keys():
        builder = _COLLECTION_BUILDERS.get(key)
        if builder is None:
            logger.warning("No collection builder registered for key '%s' – skipping", key)
            continue

        logger.info("Building documents for collection key '%s'", key)
        try:
            collection_name, documents = builder()
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to build documents for key '%s': %s", key, exc, exc_info=True)
            continue

        if collection_name in collections:
            logger.warning(
                "Collection name '%s' already populated; overwriting with latest builder output.",
                collection_name,
            )

        collections[collection_name] = documents

    return collections


def main() -> int:
    # chech qdrant connection at the start to avoid late failures
    qdrant_url = getenv("QDRANT_URL")
    key = getenv("QDRANT_API_KEY")
    if not qdrant_url or not key:
        logger.error("QDRANT_URL and QDRANT_API_KEY must be set. Script aborting.")
        return 2

    try:
        client = QdrantClient(url=qdrant_url, api_key=key, port=None)
        collections = client.get_collections()
        logger.info("Successfully connected to Qdrant. Existing collections: %s", collections)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to connect to Qdrant: %s", exc, exc_info=True)
        return 3

    collection_documents = build_collection_documents()
    load(collection_documents)
    add_site_visits_main()
    logger.info("Indexing process completed successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())


