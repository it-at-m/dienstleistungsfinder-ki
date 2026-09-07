from typing import Annotated, Any

import httpx2 as httpx
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from src.config.settings import McpSettings


def create_server(settings: McpSettings | None = None) -> MCPServer:
    settings = settings or McpSettings()
    server = MCPServer(
        "dlf-search-mcp",
        instructions=(
            "Search the Munich Dienstleistungsfinder for municipal services and administrative information. "
            "Use retrieve_munich_service_documents for questions about requirements, applications, "
            "documents, fees, deadlines, responsibilities, or contact details. "
            "Answer from the returned page_content and cite source URLs from document metadata. "
            "If results do not answer the question, say so."
        ),
        version="0.1.0",
        log_level=settings.log_level,
    )

    @server.custom_route("/healthz", methods=["GET"], include_in_schema=False)
    async def healthz(_request: Request) -> Response:
        return JSONResponse({"status": "ok", "service": "dlf-search-mcp"})

    @server.tool(
        annotations=ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=True),
    )
    async def retrieve_munich_service_documents(
        query: Annotated[str, Field(min_length=1, description="Self-contained question about Munich municipal services.")],
    ) -> dict[str, Any]:
        """Retrieve official Munich service information from the Dienstleistungsfinder.

        Use for questions about municipal services, applications, eligibility, required
        documents, fees, deadlines, responsible offices, and contacts in Munich.
        Returns full document text in page_content, source metadata for citations,
        run_id, and enhanced_query. Use the text to answer and cite the source URLs.
        This searches existing information; it does not submit applications or book appointments.
        """
        if not query.strip():
            raise ToolError("query must not be blank")
        payload = {
            "query": query,
            "result": "full",
            "collections": settings.collections,
            "enhance_query": settings.enhance_query,
            "rerank": settings.rerank,
        }
        if settings.n_results is not None:
            payload["n_results"] = settings.n_results
        # A client per call prevents backend session cookies leaking between agents.
        try:
            async with httpx.AsyncClient(timeout=settings.dlf_timeout) as client:
                response = await client.post(str(settings.dlf_retrieval_url), json=payload)
                response.raise_for_status()
                result = response.json()
        except httpx.TimeoutException:
            raise ToolError("DLF search timed out. Try again later.") from None
        except httpx.HTTPStatusError as exc:
            raise ToolError(f"DLF search failed (HTTP {exc.response.status_code}).") from None
        except httpx.RequestError:
            raise ToolError("DLF search is unavailable. Try again later.") from None
        except ValueError:
            raise ToolError("DLF search returned invalid JSON.") from None
        if not isinstance(result, dict) or not isinstance(result.get("retrieval_documents"), list):
            raise ToolError("DLF search returned an invalid retrieval response.")
        return result

    return server
