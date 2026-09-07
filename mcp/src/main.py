import json
import logging
from urllib.parse import urlsplit, urlunsplit

from src.config.settings import McpSettings
from src.server import create_server

LOGGER = logging.getLogger("dlf_search_mcp")
SERVER_NAME = "dlf-search-mcp"
SERVER_VERSION = "0.1.0"
MCP_PATH = "/mcp"


def _safe_url(value: object) -> str:
    """Return a useful URL for logs without credentials, query data, or fragments."""
    parsed = urlsplit(str(value))
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def log_startup_configuration(settings: McpSettings) -> None:
    security_mode = "configured allowlist" if settings.allowed_hosts is not None else "MCP SDK defaults"
    LOGGER.info("Starting %s version=%s", SERVER_NAME, SERVER_VERSION)
    LOGGER.info(
        "Transport configuration transport=%s host=%s port=%s path=%s stateless_http=true json_response=true",
        settings.transport,
        settings.host,
        settings.port,
        MCP_PATH,
    )
    LOGGER.info(
        "Transport security mode=%s allowed_hosts=%s allowed_origins=%s",
        security_mode,
        json.dumps(settings.allowed_hosts),
        json.dumps(settings.allowed_origins),
    )
    if settings.allowed_hosts is not None and not settings.allowed_origins:
        LOGGER.info("Origin allowlist is empty; requests without an Origin header are accepted")
    LOGGER.info(
        "Retrieval backend url=%s timeout_seconds=%s collections=%s enhance_query=%s rerank=%s n_results=%s",
        _safe_url(settings.dlf_retrieval_url),
        settings.dlf_timeout,
        json.dumps(settings.collections),
        settings.enhance_query,
        settings.rerank,
        settings.n_results,
    )


def main() -> None:
    settings = McpSettings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log_startup_configuration(settings)
    server = create_server(settings)
    if settings.transport == "stdio":
        LOGGER.info("MCP server ready on stdio")
        server.run(transport="stdio")
    else:
        LOGGER.info("MCP server listening at http://%s:%s%s", settings.host, settings.port, MCP_PATH)
        server.run(
            transport="streamable-http",
            host=settings.host,
            port=settings.port,
            streamable_http_path=MCP_PATH,
            stateless_http=True,
            json_response=True,
            transport_security=settings.transport_security,
        )


if __name__ == "__main__":
    main()
