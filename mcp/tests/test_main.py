import logging

from src.config.settings import McpSettings
from src.main import _safe_url, log_startup_configuration


def test_startup_logging_reports_effective_configuration(caplog):
    settings = McpSettings(
        _env_file=None,
        dlf_retrieval_url="https://user:secret@backend.example:8443/api/retrieval?token=private",
        dlf_timeout=42,
        transport="streamable-http",
        host="0.0.0.0",
        port=8080,
        collections=["service"],
        enhance_query=False,
        rerank=True,
        n_results=5,
        allowed_hosts=["localhost:*", "mcp.example"],
        allowed_origins=["https://client.example"],
    )

    with caplog.at_level(logging.INFO, logger="dlf_search_mcp"):
        log_startup_configuration(settings)

    messages = [record.getMessage() for record in caplog.records]
    assert "Starting dlf-search-mcp version=0.1.0" in messages
    assert any("host=0.0.0.0 port=8080 path=/mcp" in message for message in messages)
    assert any('allowed_hosts=["localhost:*", "mcp.example"]' in message for message in messages)
    assert any('allowed_origins=["https://client.example"]' in message for message in messages)
    assert any("url=https://backend.example:8443/api/retrieval" in message for message in messages)
    assert any('collections=["service"] enhance_query=False rerank=True n_results=5' in message for message in messages)
    assert all("secret" not in message and "private" not in message for message in messages)


def test_startup_logging_explains_empty_origin_allowlist(caplog):
    settings = McpSettings(_env_file=None, allowed_hosts=["mcp.example"], allowed_origins=[])

    with caplog.at_level(logging.INFO, logger="dlf_search_mcp"):
        log_startup_configuration(settings)

    assert "Origin allowlist is empty; requests without an Origin header are accepted" in caplog.messages


def test_safe_url_supports_ipv6_and_removes_sensitive_parts():
    assert _safe_url("https://user:secret@[2001:db8::1]:8443/search?token=private#fragment") == (
        "https://[2001:db8::1]:8443/search"
    )
