from datetime import datetime, timezone

import pytest
from langchain_core.documents.base import Document

from src import export_dataset_to_hf


def test_document_record_is_vector_free_and_json_safe():
    document = Document(
        id="stable-id",
        page_content="# Article",
        metadata={
            "id": 1,
            "keywords": {"beta", "alpha"},
            "lastModification": datetime(2026, 1, 2, tzinfo=timezone.utc),
            "categories": {"topic": "mobility"},
            "embedding": [0.1, 0.2],
            "sparse_vector": {"indices": [1]},
        },
    )

    assert export_dataset_to_hf._document_to_record(document) == {
        "id": 1,
        "keywords": ["alpha", "beta"],
        "lastModification": "2026-01-02T00:00:00+00:00",
        "categories": '{"topic": "mobility"}',
        "document_id": "stable-id",
        "content": "# Article",
    }


def test_export_is_skipped_when_disabled(monkeypatch):
    monkeypatch.delenv("HF_DATASET_EXPORT_ENABLED", raising=False)
    monkeypatch.setattr(
        export_dataset_to_hf,
        "_upload_documents",
        lambda *args: (_ for _ in ()).throw(AssertionError("export must be disabled")),
    )

    export_dataset_to_hf.export_datasets({"service": [Document(page_content="content")]})


def test_export_requires_token_when_enabled(monkeypatch):
    monkeypatch.setenv("HF_DATASET_EXPORT_ENABLED", "true")
    monkeypatch.delenv("HF_TOKEN", raising=False)

    with pytest.raises(ValueError, match="HF_TOKEN"):
        export_dataset_to_hf.export_datasets({})


def test_export_routes_collections_to_separate_repositories(monkeypatch):
    monkeypatch.setenv("HF_DATASET_EXPORT_ENABLED", "true")
    monkeypatch.setenv("HF_TOKEN", "test-token")
    uploads = []
    monkeypatch.setattr(
        export_dataset_to_hf,
        "_upload_documents",
        lambda repo_id, documents, token: uploads.append((repo_id, documents, token)),
    )
    service_document = Document(page_content="service")
    info_document = Document(page_content="info")

    export_dataset_to_hf.export_datasets({"service": [service_document], "info": [info_document]})

    assert uploads == [
        ("it-at-m/munich-city-services", [service_document], "test-token"),
        ("it-at-m/munich-city-info", [info_document], "test-token"),
    ]


def test_upload_verifies_existing_repository_before_pushing(monkeypatch):
    events = []

    class FakeApi:
        def __init__(self, token):
            events.append(("api", token))

        def repo_info(self, **kwargs):
            events.append(("repo_info", kwargs))

    class FakeDataset:
        def push_to_hub(self, *args, **kwargs):
            events.append(("push", args, kwargs))

    monkeypatch.setattr(export_dataset_to_hf, "HfApi", FakeApi)
    monkeypatch.setattr(
        export_dataset_to_hf.Dataset,
        "from_list",
        lambda records: events.append(("from_list", records)) or FakeDataset(),
    )

    export_dataset_to_hf._upload_documents("it-at-m/munich-city-services", [Document(page_content="content")], "token")

    assert [event[0] for event in events] == ["api", "repo_info", "from_list", "push"]
    assert events[-1][2] == {"config_name": "default", "split": "train", "token": "token"}
