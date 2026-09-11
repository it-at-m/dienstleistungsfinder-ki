# ruff: noqa: E402 (no import at top level) suppressed on this file as we need to inject the truststore before importing the other modules

from dotenv import load_dotenv
from truststore import inject_into_ssl

inject_into_ssl()
load_dotenv()

import argparse
import re
from contextlib import AsyncExitStack, asynccontextmanager

import uvicorn
from backend import backend
from fastapi import FastAPI
from fastmcp import FastMCP
from fastmcp.server.providers.openapi import MCPType, RouteMap
from settings import get_mcp_endpoints


@asynccontextmanager
async def _combined_lifespan(app, backend_lifespan, mcp_lifespan):
    async with AsyncExitStack() as stack:
        await stack.enter_async_context(backend_lifespan(backend))
        await stack.enter_async_context(mcp_lifespan(app))
        yield


def create_mcp():
    endpoints = get_mcp_endpoints()
    paths = backend.openapi()["paths"]
    for method, path in endpoints:
        if method.lower() not in paths.get(path, {}):
            raise ValueError(f"MCP_ENDPOINTS references an unknown OpenAPI operation: {method} {path}")
    return FastMCP.from_fastapi(
        app=backend,
        name="DLF MCP",
        route_maps=[
            *[RouteMap(methods=[method], pattern=f"^{re.escape(path)}$", mcp_type=MCPType.TOOL) for method, path in endpoints],
            RouteMap(pattern=r".*", mcp_type=MCPType.EXCLUDE),
        ],
    )


def create_app():
    mcp = create_mcp()
    mcp_app = mcp.http_app(path="/mcp", stateless_http=True)
    app = FastAPI(
        title="DLF Backend",
        description="Backend for the DLF MCP",
        version="0.1.0",
        openapi_url="/openapi.json",
        docs_url="/docs",
        redoc_url="/redoc",
        routes=[*mcp_app.routes, *backend.routes],
        middleware=[*backend.user_middleware],
        lifespan=lambda app: _combined_lifespan(app, backend.router.lifespan_context, mcp_app.lifespan),
    )
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--development", action="store_true", help="Run the server in development mode")
    args = parser.parse_args()

    host = "localhost" if args.development else "0.0.0.0"

    app = create_app()

    uvicorn.run(app, host=host, port=8080, log_config="logconf.yaml")
