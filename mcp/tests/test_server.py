import json

import httpx2 as httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError
from src.config.settings import McpSettings
from src.server import create_server

pytestmark = pytest.mark.anyio
TOOL = "retrieve_munich_service_documents"
RESULT = {
    "retrieval_documents": [{"page_content": "Bring your ID.", "metadata": {"source": "https://stadt.muenchen.de/service"}}],
    "run_id": "test-run",
    "enhanced_query": {"search_query": "Wohnsitz anmelden"},
}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def backend(monkeypatch):
    original_client = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr(
            "src.server.httpx.AsyncClient",
            lambda **kwargs: original_client(transport=httpx.MockTransport(handler), **kwargs),
        )

    return install


async def test_tool_discovery_has_only_query():
    server = create_server(McpSettings(_env_file=None))
    tools = await server.list_tools()
    assert [tool.name for tool in tools] == [TOOL]
    assert set(tools[0].input_schema["properties"]) == {"query"}
    assert tools[0].input_schema["required"] == ["query"]
    assert tools[0].annotations.read_only_hint is True
    assert "Munich" in tools[0].description
    assert await server.list_resources() == []
    assert await server.list_prompts() == []


async def test_forwards_full_search_and_preserves_response(backend):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, json=RESULT, headers={"set-cookie": "session=private; Path=/"})

    backend(handle)
    settings = McpSettings(
        _env_file=None,
        dlf_retrieval_url="https://backend.example/api/retrieval",
        collections=["service"],
        enhance_query=False,
        rerank=True,
        n_results=3,
    )
    server = create_server(settings)
    for _ in range(2):
        result = await server.call_tool(TOOL, {"query": "How do I register my residence?"})
        assert not result.is_error
        assert result.structured_content == RESULT
    assert len(requests) == 2
    for request in requests:
        assert request.method == "POST"
        assert str(request.url) == "https://backend.example/api/retrieval"
        assert "cookie" not in request.headers
        assert json.loads(request.content) == {
            "query": "How do I register my residence?",
            "result": "full",
            "collections": ["service"],
            "enhance_query": False,
            "rerank": True,
            "n_results": 3,
        }


async def test_backend_defaults_and_empty_results(backend):
    def handle(request):
        payload = json.loads(request.content)
        assert "n_results" not in payload
        assert payload["collections"] == "all"
        return httpx.Response(200, json={**RESULT, "retrieval_documents": []})

    backend(handle)
    result = await create_server(McpSettings(_env_file=None)).call_tool(TOOL, {"query": "a question"})
    assert not result.is_error
    assert result.structured_content["retrieval_documents"] == []


@pytest.mark.parametrize("query", ["", "   "])
async def test_blank_query_never_calls_backend(backend, query):
    def handle(request):
        pytest.fail("invalid query reached backend")

    backend(handle)
    with pytest.raises(ToolError):
        await create_server().call_tool(TOOL, {"query": query})


@pytest.mark.parametrize("failure", ["timeout", "connection", "http", "json", "shape"])
async def test_backend_errors_are_tool_errors(backend, failure):
    def handle(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("private backend details", request=request)
        if failure == "connection":
            raise httpx.ConnectError("private backend details", request=request)
        if failure == "http":
            return httpx.Response(503, text="private backend details")
        if failure == "json":
            return httpx.Response(200, text="private backend details")
        return httpx.Response(200, json=[])

    backend(handle)
    with pytest.raises(ToolError, match="DLF search") as error:
        await create_server().call_tool(TOOL, {"query": "residence registration"})
    assert "private backend details" not in str(error.value)


async def test_http_discovery_and_health():
    server = create_server()
    app = server.streamable_http_app(host="0.0.0.0", stateless_http=True, json_response=True)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://mcp") as client:
            response = await client.get("/healthz")
            assert response.json() == {"status": "ok", "service": "dlf-search-mcp"}
            response = await client.post(
                "/mcp",
                headers={"Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            )
            assert response.status_code == 200
            assert "mcp-session-id" not in response.headers
            tools = response.json()["result"]["tools"]
            assert [tool["name"] for tool in tools] == [TOOL]
            assert set(tools[0]["inputSchema"]["properties"]) == {"query"}


async def test_backend_error_is_reported_over_mcp_http(backend):
    client_class = httpx.AsyncClient
    backend(lambda request: httpx.Response(503, text="private backend details"))
    app = create_server().streamable_http_app(host="0.0.0.0", stateless_http=True, json_response=True)
    async with app.router.lifespan_context(app):
        async with client_class(transport=httpx.ASGITransport(app=app), base_url="http://mcp") as client:
            response = await client.post(
                "/mcp",
                headers={"Accept": "application/json, text/event-stream"},
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": TOOL, "arguments": {"query": "residence registration"}},
                },
            )
            assert response.status_code == 200
            result = response.json()["result"]
            assert result["isError"] is True
            assert "HTTP 503" in result["content"][0]["text"]
            assert "private backend details" not in response.text


async def test_configured_host_allowlist_accepts_container_client(monkeypatch):
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", '["localhost:*","host.docker.internal:8321"]')
    settings = McpSettings(_env_file=None)
    app = create_server(settings).streamable_http_app(
        host="127.0.0.1",
        stateless_http=True,
        json_response=True,
        transport_security=settings.transport_security,
    )
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://host.docker.internal:8321") as client:
            for host, status in [("host.docker.internal:8321", 200), ("localhost:8321", 200), ("untrusted.example:8321", 421)]:
                response = await client.post(
                    "/mcp",
                    headers={"Host": host, "Accept": "application/json, text/event-stream"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
                )
                assert response.status_code == status
                if status == 200:
                    assert response.json()["result"]["tools"][0]["name"] == TOOL
