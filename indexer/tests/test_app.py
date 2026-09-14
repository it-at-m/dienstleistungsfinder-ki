import app


def test_missing_qdrant_configuration_fails(monkeypatch):
    monkeypatch.delenv("QDRANT_URL", raising=False)
    monkeypatch.delenv("QDRANT_API_KEY", raising=False)
    assert app.main() != 0


def test_qdrant_connection_failure_fails(monkeypatch):
    monkeypatch.setenv("QDRANT_URL", "https://qdrant.example.invalid")
    monkeypatch.setenv("QDRANT_API_KEY", "test")
    monkeypatch.setattr(app, "QdrantClient", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    assert app.main() != 0


def test_export_runs_before_qdrant_loading(monkeypatch):
    events = []

    class Client:
        def get_collections(self):
            return []

    monkeypatch.setenv("QDRANT_URL", "https://qdrant.example.test")
    monkeypatch.setenv("QDRANT_API_KEY", "test")
    monkeypatch.setattr(app, "QdrantClient", lambda **kwargs: Client())
    monkeypatch.setattr(app, "build_collection_documents", lambda: {"service": []})
    monkeypatch.setattr(app, "export_datasets", lambda documents: events.append(("export", documents)))
    monkeypatch.setattr(app, "load", lambda documents: events.append(("load", documents)))
    monkeypatch.setattr(app, "add_site_visits_main", lambda: events.append(("site_visits", None)))

    assert app.main() == 0
    assert [event[0] for event in events] == ["export", "load", "site_visits"]
