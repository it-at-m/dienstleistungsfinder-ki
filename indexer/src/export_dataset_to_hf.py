"""Export transformed documents to the configured Hugging Face datasets."""

import json
from collections.abc import Mapping
from datetime import date, datetime
from os import getenv
from typing import Any

from datasets import Dataset
from huggingface_hub import HfApi
from langchain_core.documents.base import Document

from src.logtools import getLogger

logger = getLogger()

_REPOSITORIES = {
    "service": "it-at-m/munich-city-services",
    "info": "it-at-m/munich-city-info",
}
_VECTOR_METADATA_KEYS = {"embedding", "vector", "vectors", "sparse_vector", "sparse_vectors"}


def _export_enabled() -> bool:
    return getenv("HF_DATASET_EXPORT_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, set):
        return sorted(value)
    return str(value)


def _normalise_metadata_value(value: Any) -> Any:
    """Return Arrow-compatible values while keeping arbitrary nested metadata readable."""
    normalised = json.loads(json.dumps(value, default=_json_default, sort_keys=True))
    if isinstance(normalised, dict):
        return json.dumps(normalised, ensure_ascii=True, sort_keys=True)
    return normalised


def _document_to_record(document: Document) -> dict[str, Any]:
    """Build a vector-free dataset record from a transformed document."""
    record = {
        key: _normalise_metadata_value(value)
        for key, value in document.metadata.items()
        if key not in _VECTOR_METADATA_KEYS
    }
    record["document_id"] = document.id
    record["content"] = document.page_content
    return record


def _upload_documents(repo_id: str, documents: list[Document], token: str) -> None:
    """Verify an existing dataset repository and replace its default train split."""
    api = HfApi(token=token)
    api.repo_info(repo_id=repo_id, repo_type="dataset")

    dataset = Dataset.from_list([_document_to_record(document) for document in documents])
    dataset.push_to_hub(repo_id, config_name="default", split="train", token=token)


def export_datasets(collection_documents: Mapping[str, list[Document]]) -> None:
    """Export configured collections before embedding and Qdrant loading.

    The export is disabled unless ``HF_DATASET_EXPORT_ENABLED`` is truthy. When enabled,
    ``HF_TOKEN`` must grant write access to every dataset repository that receives data.
    """
    if not _export_enabled():
        logger.info("Hugging Face dataset export is disabled")
        return

    token = getenv("HF_TOKEN")
    if not token:
        raise ValueError("HF_TOKEN must be set when HF_DATASET_EXPORT_ENABLED is enabled.")

    for collection_name, repo_id in _REPOSITORIES.items():
        documents = collection_documents.get(collection_name)
        if documents is None:
            continue
        if not documents:
            logger.info("Collection '%s' produced no documents; skipping Hugging Face export", collection_name)
            continue

        logger.info(
            "Exporting %d vector-free documents from '%s' to Hugging Face dataset '%s'",
            len(documents),
            collection_name,
            repo_id,
        )
        _upload_documents(repo_id, documents, token)
