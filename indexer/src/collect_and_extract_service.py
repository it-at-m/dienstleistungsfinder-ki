import json
import os
from pathlib import Path
from time import sleep
from typing import Any

import tqdm
from dotenv import load_dotenv
from httpx import Client, HTTPError, Response, TimeoutException, TransportError

from src.data_models import DetailedArticle, ExtractionArtifact, KeywordResult
from src.generate_keywords import extract_keyword_mapping_from_collection, generate_article_keywords
from src.logtools import getLogger
from src.utils import get_with_retry

logger = getLogger()

BASE_URL = "https://stadt.muenchen.de/service/rs/befi/services/{api_id}/description/"


_failed_attempts: list[dict[str, Any]] = []
_keyword_mapping: dict[str, list[str]] | None = None

def _load_api_ids(client: Client) -> set[int] | None:
    """Loads API IDs from the API.

    Returns:
        set[int]: A set of API IDs.
    """
    API_AUTH_USER: str | None = os.getenv("API_AUTH_USER")
    API_AUTH_PASS: str | None = os.getenv("API_AUTH_PASS")
    API_IDS_URL: str | None = os.getenv("API_IDS_URL", "https://stadt.muenchen.de/service/rs/befi/services/list")

    api_ids: set[int] = set()
    auth = (API_AUTH_USER, API_AUTH_PASS) if API_AUTH_USER and API_AUTH_PASS else None

    ids_resp: Response | None = None
    try:
        if auth:
            ids_resp = get_with_retry(client, API_IDS_URL, auth=auth)
        else:
            ids_resp = get_with_retry(client, API_IDS_URL)
    except HTTPError as e:
        logger.warning(f"Error fetching API IDs: {e}.")
        ids_resp = None

    try:
        ids: dict[str, list[dict]] | None = json.loads(ids_resp.text) if ids_resp is not None else None
        if not ids:
            logger.warning("falling back to local list")
            IDS_PATH = "input/api_ids.txt"
            if not os.path.exists(IDS_PATH):
                logger.error(f"Local API IDs file not found: {IDS_PATH}")
                return None
            with open(file=IDS_PATH, mode="r") as f:
                for line in f:
                    try:
                        api_ids.add(int(line.strip()))
                    except ValueError:
                        logger.warning(f"Invalid API ID found in local list: {line.strip()}")
                        continue
        elif isinstance(ids, dict) and "ids" in list(ids.keys()) and isinstance(ids["ids"], list):
            for id in ids["ids"]:
                try:
                    api_ids.add(int(id["id"]))
                except (ValueError, TypeError) as e:
                    logger.error(f"Error parsing API ID {id}: {e}")
                    continue
        else:
            logger.error("Unable to retrieve API IDs. Neither valid response nor local list found!")
            return None
    except Exception as e:
        logger.error(f"Unexpected error occurred while fetching API IDs: {e}")
        return None

    logger.info(f"Loaded {len(api_ids)} API IDs from {API_IDS_URL}")

    return api_ids


def _extract_keywords(data: dict, article_id: int) -> tuple[list[str], dict[str, Any] | None]:
    """
    Extract categories from a nested `categoryPath -> nextLevel` chain and generate keywords for the article.

    Args:
        data (dict): Dictionary containing article information, including nested category paths.

    Returns:
        tuple:
            - list[str]: List of keywords generated for the article, filtered by confidence level.
            - dict[str, Any] | None: Dictionary containing the list of categories and the concatenated category path string,
              or None if the input data is not a dictionary.
    """
    global _keyword_mapping
    categories: list[str] = []
    if not isinstance(data, dict):
        return categories, None
    cat = data.get("categryPath")
    visited: set[int] = set()
    while isinstance(cat, dict) and id(cat) not in visited:
        visited.add(id(cat))
        name = cat.get("name")
        if isinstance(name, str) and (n := name.strip()):
            # if n.lower() != "bürgerservice":
            # every article has this category but for completeness and
            # possible extension with other articles we keep it
            categories.append(n.lower())
        cat = cat.get("nextLevel")

    category_dict: dict = {"category_list": categories, "category_path": "/".join(c for c in categories)}
    logger.debug(f"Generated category dict for article {data.get('id')}: {category_dict}")

    exsisting_keywords: list[str] | None = _keyword_mapping.get(str(article_id)) if _keyword_mapping else None
    if exsisting_keywords is not None:
        logger.debug(f"Using existing keywords from mapping for article {article_id}: {exsisting_keywords}")
        return exsisting_keywords, category_dict

    article_keywords: KeywordResult = generate_article_keywords(
        model_name=os.getenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini"),
        title=data.get("name", ""),
        description=data.get("description", ""),
        allowed_categories=categories,
    )
    keywords: list[str] = [keywords.name for keywords in article_keywords.keywords if keywords.confidence >= 0.5]
    logger.debug(f"Generated keywords for article {data.get('id')}: {keywords}")
    return keywords, category_dict


def _get_article_info(
    article_id: int, client: Client, extract: bool = False
) -> tuple[Response | dict[str, Any] | None, list[str] | None, dict[str, Any] | None]:
    """
    Fetches article information from the API and optionally extracts keywords and categories.

    Args:
        article_id (int): The ID of the article to fetch.
        client (Client): The HTTP client used to make the API request.
        extract (bool, optional): If True, extract keywords and categories from the article data. Defaults to False.

    Returns:
        tuple:
            - Response | dict[str, Any] | None: The raw response object if `extract` is False,
              or a dictionary containing article information if `extract` is True, or None in case of failure.
            - list[str] | None: A list of extracted keywords, or None if `extract` is False or in case of failure.
            - dict[str, Any] | None: A dictionary containing extracted categories, or None in case of failure.

    Notes:
        - When `extract` is True, the function returns detailed article information including sorted keywords and categories.

    """

    url = BASE_URL.format(api_id=article_id)
    global _failed_attempts
    try:
        resp: Response = get_with_retry(client, url)
        if resp.status_code != 200:
            logger.warning("Non-200 for article with id %s: Error: %s", article_id, resp.status_code)
            _failed_attempts.append(
                {
                    "article_id": article_id,
                    "status_code": resp.status_code,
                    "url": url,
                }
            )
            return None, None, None
        data = resp.json()
    except (HTTPError, TransportError, ValueError) as e:
        logger.error("Error fetching/parsing article %s: %s", article_id, e)
        _failed_attempts.append(
            {
                "article_id": article_id,
                "error": str(e),
                "url": url,
            }
        )
        return None, None, None

    keywords, categories = _extract_keywords(data, article_id)

    if not extract:
        return (
            {
                "apiUrl": url,
                "article_id": article_id,
                "name": data.get("name", "") or "",
                "keywords": sorted(keywords),
                "categories": categories,
            },
            None,
            categories,
        )
    return resp, keywords, categories


def collect_and_extract() -> list[DetailedArticle] | None:
    """Collects detailed article information from the services API.

    Returns:
        list[DetailedArticle]: A list of detailed articles.
    """
    global _failed_attempts
    global _keyword_mapping

    https_proxy: str | None = os.getenv("HTTPS_PROXY", None)
    sleep_seconds: float = float(os.getenv("REQUEST_SLEEP_SEC", "0.5"))
    timeout_sec: float = float(os.getenv("HTTP_TIMEOUT_SEC", "20"))

    detailed_articles: dict[int, DetailedArticle] = {}

    # Use context manager to ensure the client closes sockets
    with Client(proxy=https_proxy, timeout=timeout_sec, follow_redirects=True) as client:
        api_ids: set[int] | None = _load_api_ids(client)
        if not api_ids:
            logger.error("No API IDs found")
            return None

        _keyword_mapping = extract_keyword_mapping_from_collection(collection="service")
        for article_id in tqdm.tqdm(list(api_ids), desc="Collecting articles"):
            try:
                response: Any = None
                response, keywords, categories = _get_article_info(article_id, client, extract=True)
                if response and keywords and categories is not None:
                    try:
                        detailed_article = DetailedArticle.model_validate(response.json())
                        detailed_article.keywords = set(keywords)
                        detailed_article.categories = categories

                        detailed_articles[article_id] = detailed_article
                    except Exception as e:
                        logger.error("Error validating article %s: %s", article_id, e)
                        continue

            except TimeoutException as e:
                logger.warning("Timeout Error fetching article %s from API: Error: %s", article_id, e)
            finally:
                sleep(sleep_seconds)

    sorted_articles: list[DetailedArticle] = sorted(detailed_articles.values(), key=lambda article: article.name)
    logger.info("Detailed articles collected: %d", len(sorted_articles))

    return sorted_articles


def main() -> None:
    """
    Entry point of the collection script.
    Runs the data collection process and saves the collection artifact.

    Environment variables:
        EXTRACTION_FILENAME: Path to save the collection file (default: "artifacts/extraction.json").
    """
    logger.info("Collection script started")
    load_dotenv()

    # article_infos = collect()
    detailed_articles: list[DetailedArticle] | None = collect_and_extract()
    if not detailed_articles:
        logger.error("No articles found!")
        return
    extraction = ExtractionArtifact(detailed_articles=detailed_articles)

    EXTRACTION_FILENAME = os.getenv("EXTRACTION_FILENAME", "artifacts/extraction.json")
    # Ensure destination directory exists
    Path(EXTRACTION_FILENAME).parent.mkdir(parents=True, exist_ok=True)
    logger.debug("Saving extraction artifact to %s (can be specified in EXTRACTION_FILENAME)", EXTRACTION_FILENAME)
    with open(EXTRACTION_FILENAME, "w", encoding="utf-8") as file:
        file.write(extraction.model_dump_json(indent=2))

    logger.info("Extraction artifact with %d articles saved. Script finished.", len(detailed_articles))


if __name__ == "__main__":
    main()


