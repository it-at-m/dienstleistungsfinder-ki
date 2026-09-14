from os import getenv
from time import sleep

from dotenv import load_dotenv
from httpx import Client, Response, TimeoutException
from stamina import retry
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

from src.data_models import (
    ArticleInfo,
    CollectionArtifact,
    DetailedArticle,
    ExtractionArtifact,
)
from src.logtools import getLogger

logger = getLogger()


@retry(on=TimeoutException, attempts=3)
def call_with_retry(client: Client, url: str) -> Response:
    """Fetch a URL, retrying timeout failures up to three times."""
    response = client.get(url)
    return response


def extract(article_list: list[ArticleInfo]) -> list[DetailedArticle]:
    """
    Extracts detailed information for a list of articles by calling the API for each article.
    Args:
        article_list (list[ArticleInfo]): A list of ArticleInfo objects representing the articles to extract.
    Returns:
        list[DetailedArticle]: A list of DetailedArticle objects containing the extracted information.
    """
    client = Client(proxy=getenv("HTTPS_PROXY", None), timeout=10)
    detailed_articles: dict[int, DetailedArticle] = {}
    n_duplicates, n_api_errors = 0, 0
    logger.info(f"Starting API extraction for {len(article_list)} articles")
    with logging_redirect_tqdm(loggers=[logger]):
        for article_info in tqdm(article_list):
            sleep(0.5)

            try:
                response = call_with_retry(client, article_info.apiUrl)
            except TimeoutException:
                logger.warning(f"Triple Timeout for {article_info.apiUrl}; article {article_info.name}")
                n_api_errors += 1
                continue

            if response.status_code != 200:
                logger.warning(
                    f"Failed to fetch {article_info.apiUrl}; article {article_info.name}; status code: {response.status_code}"
                )
                n_api_errors += 1
                continue

            detailed_article = DetailedArticle.model_validate(response.json())

            # merge keywords from ArticleInfo and DetailedArticle by calling the union operator
            detailed_article.keywords |= article_info.keywords

            if detailed_article.id in detailed_articles:
                logger.warning(
                    f"Duplicate article id {detailed_article.id}; article {detailed_article.name}; only adding keywords."
                )
                n_duplicates += 1

                # merge keywords from duplicate articles by calling the union operator
                detailed_articles[detailed_article.id].keywords |= detailed_article.keywords
            else:
                detailed_articles[detailed_article.id] = detailed_article

    sorted_articles = sorted(detailed_articles.values(), key=lambda article: article.name)  # sort articles by id

    logger.info(
        f"Extraction finished. {len(sorted_articles)} articles extracted; {n_duplicates} duplicates; {n_api_errors} API errors"
    )
    return sorted_articles


def main():
    """
    Entry point of the extraction script.
    Reads the collection artifact, runs the extraction, and saves the extraction artifact.

    Corresponding Environment variables:
        COLLECTION_FILENAME: Path to the collection file (default: "artifacts/collection.json").
        EXTRACTION_FILENAME: Path to save the extraction file (default: "artifacts/extraction.json").
    """
    logger.info("Extraction script started")
    load_dotenv()

    COLLECTION_FILENAME = getenv("COLLECTION_FILENAME", "artifacts/collection.json")

    logger.debug(f"Loading collection artifact from {COLLECTION_FILENAME} (can be specified in COLLECTION_FILENAME)")
    with open(COLLECTION_FILENAME, "r", encoding="utf-8") as file:
        collection = CollectionArtifact.model_validate_json(file.read())
    logger.info(f"Collection artifact with {len(collection.article_infos)} articles loaded")

    detailed_articles = extract(collection.article_infos)
    MIN_ARTICLES = int(getenv("DLF_INDEXER_MIN_ARTICLES", 800))

    if len(detailed_articles) < MIN_ARTICLES:
        logger.error(
            f"Too few articles extracted: Got {len(detailed_articles)}, expected at least {MIN_ARTICLES}. Script aborting."
        )
        exit(-1)

    extraction = ExtractionArtifact(detailed_articles=detailed_articles)

    EXTRACTION_FILENAME = getenv("EXTRACTION_FILENAME", "artifacts/extraction.json")
    logger.debug(f"Saving extraction artifact to {EXTRACTION_FILENAME} (can be specified in EXTRACTION_FILENAME)")
    with open(EXTRACTION_FILENAME, "w", encoding="utf-8") as file:
        file.write(extraction.model_dump_json(indent=2))

    logger.info(f"Extraction artifact with {len(detailed_articles)} articles saved. Script finished.")


if __name__ == "__main__":
    main()
