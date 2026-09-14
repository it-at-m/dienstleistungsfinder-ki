# ruff: noqa: E402 (no import at top level) suppressed on this file as we need to inject the truststore before importing the other modules
from truststore import inject_into_ssl  # noqa

import re

inject_into_ssl()  # noqa

import datetime as dt
import time
from os import getenv
from typing import Any

import httpx
import stamina
from langchain_core.documents.base import Document
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from langchain_qdrant import FastEmbedSparse, QdrantVectorStore, RetrievalMode
from openai import APITimeoutError, RateLimitError
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    Modifier,
    SnapshotDescription,
    SparseVectorParams,
    VectorParams,
)
from tqdm import tqdm

# from langchain_text_splitters import MarkdownHeaderTextSplitter
from src.logtools import getLogger
from src.utils import build_collection_content_hash_map, extract_modified_and_new_docs

logger = getLogger()


def _snapshot_creation_time(snapshot_name: str) -> dt.datetime | None:
    """Returns the creation time of a snapshot as a datetime object."""
    m = re.search(r"\b(\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2})\b", snapshot_name)
    if not m:
        return None
    logger.debug(f"Extracted creation time string: {m.group(1)}")
    return dt.datetime.strptime(m.group(1), "%Y-%m-%d-%H-%M-%S")


def _split_equal_chunks(lst: list[Any], chunk_size: int) -> list[list[Any]] | None:
    """
    Splits the given list into equal chunks of the given size.

    Parameters:
        lst (list[Any]): The list to split.
        chunk_size (int): The size of each chunk.
    """
    if not lst or chunk_size <= 0:
        return None
    return [lst[i : i + chunk_size] for i in range(0, len(lst), chunk_size)]


def _build_embedding_model() -> tuple[Embeddings, int]:
    """Builds and returns an instance of the OpenAIEmbeddings model for OpenAI text embedding.

    Returns:
        embedding_model (Embeddings): An instance of the OpenAIEmbeddings model.
        dimension (int): The dimension of the embeddings.

    Corresponding Environment Variables:
        OPENAI_EMBEDDING_MODEL: The model to use for the OpenAI API.
        OPENAI_API_KEY: The API key for the OpenAI API.
        OPENAI_API_BASE: Base URL of the LiteLLM Proxy.
        EMB_MAX_RETRIES: The maximum number of retries for the OpenAI API.
        EMB_TIMEOUT: The timeout for the OpenAI API.
    """
    MODEL: str | None = getenv("OPENAI_EMBEDDING_MODEL")
    TIMEOUT: int = int(getenv("EMB_TIMEOUT", 10))
    MAX_RETRIES: int = int(getenv("EMB_MAX_RETRIES", 2))

    if MODEL is None:
        raise ValueError("OPENAI_EMBEDDING_MODEL environment variable must be set.")

    try:
        embedding_model = OpenAIEmbeddings(
            model=MODEL,
            timeout=TIMEOUT,
            max_retries=MAX_RETRIES,
        )

        test_embedding = embedding_model.embed_query("test")
    except Exception as e:
        logger.error(f"Failed to create embedding model with error: {e}. Exiting load script.")
        raise e
    return embedding_model, len(test_embedding)


def _build_sparse_embedding_model() -> FastEmbedSparse:
    """
    Builds BM25 embedding model in german language for the sparse vectors.
    """
    SPARSE_MODEL_NAME = getenv("EMB_SPARSE_MODEL", "Qdrant/bm25")
    sparse_embedding_model = FastEmbedSparse(
        model_name=SPARSE_MODEL_NAME,
        language="german",
        cache_dir="./model_cache",
    )
    return sparse_embedding_model


def _build_vectorstore(
    embedding_model: Embeddings,
    dimension: int,
    sparse_embedding_model: FastEmbedSparse,
    collection_name: str | None = None,
) -> tuple[QdrantVectorStore, dict | None]:
    """
    Builds a Qdrant vector store using the given embedding model.

    Parameters:
        embedding_model (Embeddings): The embedding model to use for building the vector store.
        dimension (int): The dimension of the embeddings.

    Returns:
        VectorStore: The built vector store.

    Corresponding Environment Variables:
        QDRANT_API_KEY: The API key for the Qdrant API.
        QDRANT_URL: The URL for the Qdrant Instance.
        VDB_COLLECTION_NAME: The name of the collection to use for the vector store.
        VDB_MAX_SNAPSHOTS: The maximum number of snapshots to keep in the collection.
        VDB_NUM_REPLICAS: The number of replicas to use for the collection.
        VDB_NUM_SHARDS: The number of shards to use for the collection.
    """
    QDRANT_URL = getenv("QDRANT_URL")
    QDRANT_API_KEY = getenv("QDRANT_API_KEY")
    TIMEOUT = int(getenv("VDB_TIMEOUT", 100))
    COLLECTION_NAME = collection_name if collection_name else getenv("VDB_COLLECTION_NAME", "service")
    DENSE_VECTOR_NAME = getenv("VDB_DENSE_VECTOR_NAME", "dense")
    SPARSE_VECTOR_NAME = getenv("VDB_SPARSE_VECTOR_NAME", "sparse")
    MAX_SNAPSHOTS = int(getenv("VDB_MAX_SNAPSHOTS", 10))
    NUM_REPLICAS = int(getenv("VDB_NUM_REPLICAS", 1))
    NUM_SHARDS = int(getenv("VDB_NUM_SHARDS", 1))
    DEL_COLLECTION = getenv("VDB_DEL_COLLECTION", "false").lower() == "true"

    # Create a Qdrant client with the given URL and API key
    qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY, port=None, timeout=TIMEOUT)
    content_hash_map = {}

    logger.debug("Checking if the collection exists")
    if qdrant_client.collection_exists(COLLECTION_NAME):
        logger.info(f"Collection {COLLECTION_NAME} already exists. Snapshotting and clearing it.")

        create_snapshot: bool = False

        # List all exisiting snapshots and sort them by creation time
        snapshots: list[SnapshotDescription] = qdrant_client.list_snapshots(COLLECTION_NAME)
        if len(snapshots) == 0:
            logger.info("No snapshots found, creating a new snapshot")
            create_snapshot = True
        else:
            try:
                sorted_snapshots = sorted(
                    snapshots,
                    key=lambda snapshot: snapshot.creation_time or dt.datetime.min,
                    reverse=True,
                )
                latest_snapshot_time = dt.datetime.fromisoformat(sorted_snapshots[0].creation_time + "Z")  # type: ignore
            except Exception as e:
                logger.warning(f"Failed to log snapshot creation details: {e}; falling back to regex-based sorting")
                sorted_snapshots = sorted(
                    snapshots,
                    key=lambda snapshot: _snapshot_creation_time(snapshot.name) or dt.datetime.min,
                    reverse=True,
                )
                latest_snapshot_time = dt.datetime.fromisoformat(_snapshot_creation_time(sorted_snapshots[0]) + "Z")  # type: ignore

            # Check if we have to make a new snapshot (latest one is older than 12 hours)
            # Calculate time difference between current time and latest snapshot time
            time_difference: dt.timedelta = dt.datetime.now(dt.timezone.utc) - latest_snapshot_time
            logger.debug(
                f"Latest snapshot time: {latest_snapshot_time}, Current time: {dt.datetime.now(dt.timezone.utc)}, Time difference: {time_difference}"
            )
            if time_difference < dt.timedelta(hours=12):
                logger.info("Latest snapshot is less than 12 hours old, skipping snapshot creation")
            else:
                logger.info("Creating a new snapshot as the latest snapshot is older than 12 hours")
                create_snapshot = True

                # Delete all snapshots except the latest max_snapshots-1 (we will create one more next so its max_snapshots again)
                snapshot_index = MAX_SNAPSHOTS - 1
                if len(snapshots) > snapshot_index:
                    for snapshot in sorted_snapshots[snapshot_index:]:
                        qdrant_client.delete_snapshot(COLLECTION_NAME, snapshot.name)

        if create_snapshot:
            qdrant_client.create_snapshot(COLLECTION_NAME)

        # Clear the collection by deleting it only if configured to do so
        # To reduce cost of upserts by keeping the collection and just upserting new/updated documents, we skip deletion by default
        if DEL_COLLECTION:
            qdrant_client.delete_collection(COLLECTION_NAME, timeout=120)
        else:
            # scroll through existing collection to build content hash map to upsert only new/updated documents
            content_hash_map = build_collection_content_hash_map(qdrant_client, COLLECTION_NAME)
            vectorstore = QdrantVectorStore(
                client=qdrant_client,
                collection_name=COLLECTION_NAME,
                retrieval_mode=RetrievalMode.HYBRID,
                vector_name=DENSE_VECTOR_NAME,
                embedding=embedding_model,
                sparse_vector_name=SPARSE_VECTOR_NAME,
                sparse_embedding=sparse_embedding_model,
            )
            return vectorstore, content_hash_map

    # Create the collection with the new vector params
    qdrant_client.create_collection(
        COLLECTION_NAME,
        vectors_config={DENSE_VECTOR_NAME: VectorParams(size=dimension, distance=Distance.COSINE)},
        sparse_vectors_config={
            # IDF Modifier for sparse vectors, only when needed by model: https://qdrant.github.io/fastembed/examples/Supported_Models/#supported-sparse-text-embedding-models
            SPARSE_VECTOR_NAME: SparseVectorParams(modifier=Modifier.IDF)
        },
        replication_factor=NUM_REPLICAS,
        shard_number=NUM_SHARDS,
    )

    # Create the vector store from the client
    vectorstore = QdrantVectorStore(
        client=qdrant_client,
        collection_name=COLLECTION_NAME,
        retrieval_mode=RetrievalMode.HYBRID,
        vector_name=DENSE_VECTOR_NAME,
        embedding=embedding_model,
        sparse_vector_name=SPARSE_VECTOR_NAME,
        sparse_embedding=sparse_embedding_model,
    )

    return vectorstore, None


# by default backoff is computed as:
#   min(timeout, wait_initial * wait_exp_base ** (attempts - 1) + jitter (defaults to 1))
# https://stamina.hynek.me/en/stable/api.html#module-stamina
@stamina.retry(
    on=(
        # Exception,
        httpx.ReadTimeout,
        APITimeoutError,
        RateLimitError,
    ),
    attempts=20,
    wait_initial=10,
    wait_exp_base=2,
    timeout=86400,  # maximum delay between retries
)
def _upsert_batch(vectorstore: QdrantVectorStore, batch: list[Document], **kwargs) -> None:
    vectorstore.add_documents(batch, **kwargs)


def load(collection_documents: dict[str, list[Document]]) -> None:
    """Create or update Qdrant collections from the supplied documents."""
    logger.info("Load operation started with %d configured collections", len(collection_documents))

    if not collection_documents:
        logger.warning("No collection documents provided; nothing to load")
        return

    embedding_model, dimension = _build_embedding_model()
    sparse_embedding_model = _build_sparse_embedding_model()
    logger.info("Embedding and sparse models initialized")

    chunk_size = int(getenv("VDB_BATCH_SIZE", "25"))
    chunk_pause = float(getenv("VDB_BATCH_PAUSE_SEC", "0"))

    for collection_name, documents in collection_documents.items():
        if not documents:
            logger.info("Collection '%s' produced no documents – skipping", collection_name)
            continue

        logger.info(
            "Creating vector store '%s' with %d documents (chunk size %d)", collection_name, len(documents), chunk_size
        )
        vectorstore, content_hash_map = _build_vectorstore(
            embedding_model,
            dimension,
            sparse_embedding_model,
            collection_name,
        )
        # remove documents that are already in the collection with the same content hash
        docs_to_update = {}
        if content_hash_map is not None:
            original_count = len(documents)
            docs_to_update, documents = extract_modified_and_new_docs(documents, content_hash_map)
            new_count = len(documents)
            logger.info(
                f"Upserting {new_count} new Documents, and updating {len(docs_to_update)} modified documents into collection '{collection_name}'"
            )
            logger.info(f"Updating: {new_count + len(docs_to_update)} Documents out of: {original_count}")

        doc_chunks = _split_equal_chunks(documents, chunk_size)
        # upsert new documents in chunks with retry and exponential backoff
        if doc_chunks is not None:
            for chunk in tqdm(doc_chunks, desc=f"Upserting {collection_name}", leave=False):
                try:
                    _upsert_batch(vectorstore, chunk)
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "Error adding documents to collection '%s': %s",
                        collection_name,
                        exc,
                        exc_info=True,
                    )
                    for doc in chunk:
                        logger.error("Failed document: %s", doc.metadata.get("source", doc.metadata))
                    time.sleep(30)
            if chunk_pause > 0:
                time.sleep(chunk_pause)

        # update modified documents in chunks with retry and exponential backoff
        if docs_to_update:
            update_items = list(docs_to_update.items())
            update_chunks = _split_equal_chunks(update_items, chunk_size)
            if update_chunks is not None:
                for chunk in tqdm(update_chunks, desc=f"Updating modified documents in {collection_name}", leave=False):
                    ids = [pt_id for pt_id, _ in chunk]
                    docs = [doc for _, doc in chunk]
                    try:
                        _upsert_batch(vectorstore, docs, ids=ids)
                    except Exception as exc:  # noqa: BLE001
                        logger.error(
                            "Error updating documents in collection '%s': %s",
                            collection_name,
                            exc,
                            exc_info=True,
                        )
                        for doc in docs:
                            logger.error("Failed document: %s", doc.metadata.get("source", doc.metadata))
                        time.sleep(30)

    logger.info("Load operation finished")


def main() -> None:
    """Entry point reserved for future use; prefer invoking via app.py."""
    logger.error("Direct execution is no longer supported. Use app.py to orchestrate document building and loading.")


if __name__ == "__main__":
    main()
