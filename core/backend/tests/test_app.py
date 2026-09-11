import asyncio
import os
from contextlib import asynccontextmanager

os.environ.setdefault("DLF_SESSION_SECRET", "test-session-secret")
os.environ.setdefault("LANGFUSE_PUBLIC_KEY", "test-public")
os.environ.setdefault("LANGFUSE_SECRET_KEY", "test-secret")
os.environ.setdefault("LANGFUSE_HOST", "https://langfuse.example.invalid")

from app import _combined_lifespan, create_app
from backend import _get_session_id, backend
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import JSONResponse

client = TestClient(backend)


def test_combined_lifespan_starts_backend_before_mcp():
    events = []

    @asynccontextmanager
    async def backend_lifespan(app):
        events.append("backend-start")
        yield
        events.append("backend-stop")

    @asynccontextmanager
    async def mcp_lifespan(app):
        events.append("mcp-start")
        yield
        events.append("mcp-stop")

    async def run_lifespan():
        async with _combined_lifespan(object(), backend_lifespan, mcp_lifespan):
            events.append("running")

    asyncio.run(run_lifespan())

    assert events == ["backend-start", "mcp-start", "running", "mcp-stop", "backend-stop"]


def test_wrapped_app_uses_stateless_mcp_http():
    app = create_app()
    mcp_route = next(route for route in app.routes if getattr(route, "path", None) == "/mcp")

    assert mcp_route.methods == {"POST", "DELETE"}


def test_wrapped_app_installs_session_middleware():
    app = create_app()

    def get_session_id(request: Request) -> JSONResponse:
        return JSONResponse({"id": _get_session_id(request)})

    app.router.add_route("/test-session", get_session_id)
    app.router.routes.insert(0, app.router.routes.pop())

    response = TestClient(app).get("/test-session")

    assert response.status_code == 200
    assert response.json()["id"]


def test_healthz():
    response = client.get("/api/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_static_index():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "<dlf-search-webcomponent>" in response.text
    assert "Build the frontend or run the core container" not in response.text


def test_mcp_exposes_only_retrieval():
    from app import create_mcp
    from fastmcp import Client

    async def discover():
        async with Client(create_mcp()) as mcp_client:
            tools = await mcp_client.list_tools()
            assert [tool.name for tool in tools] == ["retrieve_munich_service_documents"]
            assert "result='full'" in tools[0].description
            assert "source URLs" in tools[0].description
            assert await mcp_client.list_resources() == []
            assert await mcp_client.list_resource_templates() == []

    asyncio.run(discover())


def test_mcp_allowlist_matches_exact_path_and_method(monkeypatch):
    import app as app_module
    from fastapi import FastAPI
    from fastmcp import Client

    api = FastAPI()
    for path, method, name in [
        ("/api/retrieval", "POST", "allowed"),
        ("/api/retrieval", "GET", "wrong_method"),
        ("/api/retrieval/admin", "POST", "wrong_path"),
        ("/api/new", "POST", "new_endpoint"),
    ]:
        api.add_api_route(path, lambda: {}, methods=[method], operation_id=name)
    monkeypatch.setattr(app_module, "backend", api)

    async def discover():
        async with Client(app_module.create_mcp()) as mcp_client:
            assert [tool.name for tool in await mcp_client.list_tools()] == ["allowed"]

    asyncio.run(discover())


def test_scrubber_is_removed():
    schema = backend.openapi()
    assert "/api/scrub" not in schema["paths"]
    assert "ScrubInput" not in schema["components"]["schemas"]
    assert "scrubber_enabled" not in schema["components"]["schemas"]["FrontendConfig"]["properties"]
