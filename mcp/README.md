# DLF Search MCP

A small MCP Python SDK v2 server exposing exactly one tool:
`retrieve_munich_service_documents(query: str)`.

The tool searches Munich municipal services and administrative information by
calling the existing DLF backend's `POST /api/retrieval`. Its description tells
agents when to use it and to answer from the returned document text with source
citations. It always requests `result: "full"` and preserves the backend response
(`retrieval_documents`, `run_id`, `enhanced_query`). Search runs entirely in the
backend; the MCP server needs no Qdrant, embedding, or reranker credentials.

## Run locally

From this directory:

```bash
cp .env.example .env
uv sync --locked
uv run dlf-search-mcp
```

Connect an MCP client using Streamable HTTP at `http://localhost:8081/mcp`.
The local backend defaults to port 8080. For stdio, set `MCP_TRANSPORT=stdio`.

## Configuration

Environment variables take precedence over `.env` in the working directory.
Only `query` is agent-controlled. Retrieval tuning belongs to the deployment:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DLF_RETRIEVAL_URL` | `http://localhost:8080/api/retrieval` | Complete backend retrieval URL |
| `DLF_TIMEOUT` | `60` | Backend timeout in seconds |
| `MCP_COLLECTIONS` | all | Optional JSON list, e.g. `["service","info"]` |
| `MCP_ENHANCE_QUERY` | `true` | Backend query enhancement |
| `MCP_RERANK` | `false` | Request backend reranking; backend overrides still apply |
| `MCP_N_RESULTS` | unset | Result limit from 1 to 20; unset uses backend default |
| `MCP_TRANSPORT` | `streamable-http` | Streamable HTTP or `stdio` |
| `MCP_HOST` | `0.0.0.0` | Bind address |
| `MCP_PORT` | `8081` (container: `8080`) | Listening port |
| `MCP_LOG_LEVEL` | `INFO` | SDK logging level |
| `MCP_ALLOWED_HOSTS` | SDK default | Optional JSON list of accepted HTTP Host headers; enables DNS rebinding protection |
| `MCP_ALLOWED_ORIGINS` | `[]` | Accepted Origin headers when a host allowlist is configured; absent Origin headers are accepted |

Keep queries concise; the backend enforces its configured query length limit
(default 300 characters). Each tool call has its own HTTP client and backend
session cookies. HTTP errors, timeouts, and invalid responses become tool errors.
The server does not expose filtering, scrubbing, answer generation, or feedback
tools. `/healthz` checks the MCP process, independently of backend availability.

## Container image and OpenShift

The **Release MCP image** GitHub Actions workflow builds and publishes to
`ghcr.io/<repository-owner>/<repository-name>-mcp` (lowercase):

- Push `mcp-v0.1.0` to publish `:0.1.0`, `:latest`, and `:sha-<commit>`.
- Push an `mcp-test-*` tag from a feature branch to publish only `:sha-<commit>`.
- Run the workflow manually to publish only `:sha-<commit>`.

Until the workflow exists on the repository's default branch, GitHub does not
show its manual **Run workflow** button. Trigger the same SHA-only build from a
feature branch with a temporary tag instead:

```bash
git tag mcp-test-<name>
git push origin mcp-test-<name>
```

After testing, delete the temporary tag locally and remotely:

```bash
git tag -d mcp-test-<name>
git push origin --delete mcp-test-<name>
```

Both release and CI run lint and tests. CI also builds the image without publishing.
To build locally from the repository root:

```bash
docker build -t dlf-mcp:local mcp
```

The image uses the same pinned UBI 10 Minimal base and Python version as the
backend. Build-time `uv` installs Python under `/opt/python` so arbitrary UIDs
can access the interpreter. The runtime contains Python and the MCP environment.

The container listens on port 8080, supports OpenShift's assigned UID, and does
not need a writable root filesystem. HTTP is stateless, so replicas need no
sticky sessions.

Edit `openshift.yaml` to use your published image (prefer a version or digest)
and your backend Service URL, then apply it to your namespace:

```bash
oc apply -n YOUR_NAMESPACE -f mcp/openshift.yaml
```

The example creates a Deployment and an internal Service. In-cluster clients use
`http://dlf-mcp:8080/mcp`. For local access:

```bash
oc port-forward -n YOUR_NAMESPACE service/dlf-mcp 8081:8080
```

If the GHCR package is private, configure an image pull secret in your namespace.
For external agents, add a Route using your namespace's access controls and a
proxy timeout longer than `DLF_TIMEOUT`. This server has no built-in client
authentication; the example keeps it internal.

## Development

```bash
uv run ruff check .
uv run pytest
```

The implementation uses the official [MCP SDK v2 API](https://py.sdk.modelcontextprotocol.io/migration/)
(`MCPServer`, with transport options passed to `run`).

## Container clients and HTTP 421

A client in a container must use a reachable host address, such as
`http://host.docker.internal:8321/mcp`, rather than its own `localhost`.
If the server logs `Invalid Host header` and returns HTTP 421, the connection
works but the SDK's DNS rebinding protection rejects the requested hostname.
Add the exact client-facing host and port to `mcp/.env`, retaining local access:

```dotenv
MCP_ALLOWED_HOSTS=["localhost:*","127.0.0.1:*","host.docker.internal:8321"]
```

Restart `uv run dlf-search-mcp` from the `mcp` directory. Use your actual listening
port in the client URL and allowlist. For OpenShift, the same setting can allow
Service DNS names or a Route hostname (usually without a port for HTTPS).
If a browser client sends an Origin header, also configure its exact origin in
`MCP_ALLOWED_ORIGINS`. Host entries omit the scheme; Origin entries include it.
