# MCP integration in Core

Core includes a FastMCP server in the same process and container as the FastAPI backend. It exposes the Streamable HTTP endpoint `/mcp` on port 8080.

```text
MCP client ──► Core /mcp (FastMCP) ──► Core retrieval chain
```

## Run and connect

Configure Core as described in [Local development](./local-development), then start it from the repository root:

```shell
docker compose up --build core
```

A client running on the host connects to `http://localhost:8080/mcp`. For a client in another Docker container, use a hostname reachable from that container, such as `http://host.docker.internal:8080/mcp` for Core's published host port, or `http://core:8080/mcp` on a shared Docker network. Inside the client container, `localhost` refers to the client container itself.

For MUCGPT, configure:

```yaml
MCP:
  SOURCES:
    DLF:
      url: "http://host.docker.internal:8080/mcp"
      transport: "streamable_http"
```

On Linux Docker Engine, the client container may need `extra_hosts: ["host.docker.internal:host-gateway"]`. Core's normal `python app.py` launch binds to `0.0.0.0:8080`; `--development` binds only to localhost. Use `/api/healthz` to check Core's health.

## Exposed tool

Only `retrieve_munich_service_documents` is exposed initially. It searches official Munich service information without submitting applications or booking appointments.

Supply a self-contained `query` and explicitly set `result="full"` when the assistant needs document text to answer. The API default, `minimal`, returns compact document references and metadata. Keep `enhance_query=true` and `collections="all"` for general searches; omit keyword and category filters unless their exact valid values are known. Answer from the retrieved text and cite its source URLs.

## Configure exposure

`MCP_ENDPOINTS` in `core/backend/app.py` is an explicit HTTP method/path allowlist:

```python
MCP_ENDPOINTS = (("POST", "/api/retrieval"),)
```

Each entry becomes a FastMCP tool. A final exclusion rule prevents all other endpoints from becoming MCP tools or resources. Add an explicit method/path entry to expose another endpoint, then rebuild or restart Core and refresh the client's cached tool list.

## Deployment

MCP is shipped in `ghcr.io/it-at-m/dienstleistungsfinder-ki-core:<version>` through the Core release workflow. Route `/mcp` to the same Core service and port as the HTTP API. It uses Core's environment configuration and startup lifecycle. Protect externally exposed endpoints with the deployment platform's authentication and authorization controls.
