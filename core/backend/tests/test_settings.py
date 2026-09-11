import pytest
from settings import get_mcp_endpoints


def test_mcp_default(monkeypatch):
    monkeypatch.delenv("MCP_ENDPOINTS", raising=False)
    assert get_mcp_endpoints() == (("POST", "/api/retrieval"),)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-json",
        "null",
        "{}",
        '["POST /api/retrieval"]',
        "[{}]",
        '[{"method":"*","path":"/api/retrieval"}]',
        '[{"method":null,"path":"/api/retrieval"}]',
        '[{"method":"POST","path":null}]',
        '[{"method":"POST","path":"api/retrieval"}]',
        '[{"method":"POST","path":"/api/retrieval?x=1"}]',
        '[{"method":"POST","path":"/api/retrieval","extra":true}]',
    ],
)
def test_invalid_mcp_configuration_fails(monkeypatch, value):
    monkeypatch.setenv("MCP_ENDPOINTS", value)
    with pytest.raises(ValueError, match="MCP_ENDPOINTS"):
        get_mcp_endpoints()


@pytest.mark.parametrize("method,path", [("GET", "/api/retrieval"), ("POST", "/api/missing"), ("POST", "/api/.*")])
def test_unknown_mcp_operation_fails(monkeypatch, method, path):
    import json

    from app import create_mcp

    monkeypatch.setenv("MCP_ENDPOINTS", json.dumps([{"method": method, "path": path}]))
    with pytest.raises(ValueError, match="unknown OpenAPI operation"):
        create_mcp()
