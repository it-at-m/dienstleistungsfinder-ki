"""Backend settings loaded from environment variables (including app.py's .env)."""

import json
from os import getenv


def get_mcp_endpoints() -> tuple[tuple[str, str], ...]:
    """Read exact method/path pairs; an empty list disables all MCP tools."""
    value = getenv("MCP_ENDPOINTS", '[{"method":"POST","path":"/api/retrieval"}]')
    try:
        entries = json.loads(value)
    except json.JSONDecodeError as exc:
        raise ValueError("MCP_ENDPOINTS must be a JSON list of objects with method and path fields") from exc
    if not isinstance(entries, list):
        raise ValueError("MCP_ENDPOINTS must be a JSON list of objects with method and path fields")

    endpoints = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"method", "path"}:
            raise ValueError("Each MCP_ENDPOINTS entry must contain exactly method and path")
        method, path = entry["method"], entry["path"]
        if not isinstance(method, str) or method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE"}:
            raise ValueError("MCP_ENDPOINTS method must be an HTTP method")
        if not isinstance(path, str) or not path.startswith("/") or "?" in path or "#" in path:
            raise ValueError("MCP_ENDPOINTS path must be an exact API path starting with /, without a query or fragment")
        endpoint = (method.upper(), path)
        if endpoint not in endpoints:
            endpoints.append(endpoint)
    return tuple(endpoints)
