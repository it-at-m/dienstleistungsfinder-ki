import hashlib
import re
from os import getenv
from typing import Any

import pandas as pd
from httpx import Client, HTTPError, Response
from langchain_core.documents.base import Document
from qdrant_client import QdrantClient
from stamina import retry

from src.logtools import getLogger

logger = getLogger()


# by default backoff is computed as:
#   min(timeout, wait_initial * wait_exp_base ** (attempts - 1) + jitter (defaults to 1))
# https://stamina.hynek.me/en/stable/api.html#module-stamina
@retry(on=(HTTPError), attempts=3)
def get_with_retry(client: Client, url: str, **kwargs) -> Response:
    response = client.get(url, **kwargs)
    response.raise_for_status()
    return response


def _extract_id_service(url: str | None) -> int | None:
    """Extract an article id from the given URL string."""
    if url is None or pd.isna(url):
        return None

    _STRIP_HOST_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://[^/]+")
    _SERVICE_ID_RE = re.compile(r"/service/info/[^/]+/(?P<id>\d{4,})/(?:n0/)?(?:$|[?#])")

    normalized = _STRIP_HOST_RE.sub("", str(url))
    if not normalized.startswith("/"):
        normalized = "/" + normalized

    match = _SERVICE_ID_RE.search(normalized)
    if match:
        return int(match.group("id"))
    return None


def _build_visits_map_from_df(csv_path: str) -> dict[int, int]:
    """Aggregate visit counts per article id from the configured CSV export."""
    per_id_max: dict[int, int] = {}

    for chunk in pd.read_csv(
        csv_path,
        chunksize=100_000,
        delimiter=";",
        usecols=["URL", "Besuche"],
        dtype={"URL": "string"},
    ):
        ids = [_extract_id_service(url) for url in chunk["URL"].dropna().astype("string")]
        visits = [int(count) for count in chunk["Besuche"][1:]]

        df = pd.DataFrame({"extracted_id": ids, "Besuche": visits}).dropna(subset=["extracted_id", "Besuche"])
        local = df.groupby("extracted_id", sort=False)["Besuche"].max().astype("int64").to_dict()

        for key, value in local.items():
            previous = per_id_max.get(key)
            if previous is None or value > previous:
                per_id_max[int(key)] = value

    return per_id_max


def _configured_collection_keys() -> set[str]:
    return set(list(getenv("VDB_COLLECTIONS", "service,info").split(",")))


def _hash_content(content: str) -> str:
    """Hash the given content string using a simple hash function."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _normalize_content(content: str) -> str:
    """Normalize the given content string by stripping whitespace, collapsing multiple spaces and lowercasing."""
    return re.sub(r"\s+", " ", content.strip()).lower()


def extract_modified_and_new_docs(
    docs: list[Document],
    content_hash_map: dict[str, str],
) -> tuple[dict[str, Document], list[Document]]:
    """Split docs into modified (needs upsert by id) and new (insert) sets.

    The content hash map is keyed by document/point id and stores the last indexed content hash.
    """
    docs_to_update: dict[str, Document] = {}
    new_docs: list[Document] = []

    for doc in docs:
        doc_id = str(doc.id) if doc.id is not None else ""
        if not doc_id:
            # No stable id available; treat as new to avoid accidental overwrites
            new_docs.append(doc)
            continue

        content_hash = _hash_content(_normalize_content(doc.page_content))
        existing_hash = content_hash_map.get(doc_id)

        if existing_hash is None:
            new_docs.append(doc)
        elif existing_hash != content_hash:
            docs_to_update[doc_id] = doc
        # else: unchanged -> skip

    return docs_to_update, new_docs


def build_collection_content_hash_map(qdrant_client: QdrantClient, collection: str) -> dict[str, str]:
    """Build a mapping of point ids to content hashes for a collection."""
    content_hash_map: dict[str, str] = {}

    # scroll through qdrant collections and build a mapping of point ids to content hashes for a collection.
    offset = 0
    while offset is not None:
        points, offset = qdrant_client.scroll(collection_name=collection, offset=offset, limit=1000, with_payload=True)
        if not points:
            break
        offset = offset or None

        for point in points:
            payload: dict[str, Any] = point.payload or {}
            point_id = point.id  # same id that is created for each document, i.e. document.id == point.id
            content = payload.get("page_content")
            if point_id is not None and content is not None:
                content_hash = _hash_content(_normalize_content(content))
                content_hash_map[str(point_id)] = content_hash

    return content_hash_map
