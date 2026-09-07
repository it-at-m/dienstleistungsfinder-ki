# MCP server

The MCP server makes Dienstleistungsfinder retrieval available to MCP-compatible agents. It is a small, stateless adapter: clients call an MCP tool, the server sends the query to the Core retrieval API, and the complete retrieval result is returned to the client.

```text
MCP client ──► Streamable HTTP /mcp ──► MCP server ──► POST /api/retrieval ──► Core
```

It does not connect directly to Qdrant, embedding models, rerankers, or Langfuse. Those responsibilities remain in Core.

## Tool

The server exposes exactly one read-only tool:

| Tool                                | Input                               | Result                                                                |
| ----------------------------------- | ----------------------------------- | --------------------------------------------------------------------- |
| `retrieve_munich_service_documents` | A non-empty, self-contained `query` | Full documents, source metadata, run ID, and enhanced query from Core |

Agents should use the returned document text to answer and cite URLs from the metadata. The tool searches existing information; it does not submit applications or book appointments.

## Run locally

The server requires Python 3.13 and [uv](https://docs.astral.sh/uv/). Run commands from the `mcp` directory so Pydantic loads `mcp/.env`:

```shell
cd mcp
cp .env.example .env
uv sync --locked
uv run dlf-search-mcp
```

The default Streamable HTTP endpoint is `http://localhost:8081/mcp`; `GET /healthz` is the health endpoint. Set `MCP_TRANSPORT=stdio` for a local stdio client.

## Configuration

Environment variables override values from `.env` in the current working directory.

| Variable              | Default                               | Purpose                                                 |
| --------------------- | ------------------------------------- | ------------------------------------------------------- |
| `DLF_RETRIEVAL_URL`   | `http://localhost:8080/api/retrieval` | Complete Core retrieval URL                             |
| `DLF_TIMEOUT`         | `60`                                  | Core request timeout in seconds                         |
| `MCP_TRANSPORT`       | `streamable-http`                     | `streamable-http` or `stdio`                            |
| `MCP_HOST`            | `0.0.0.0`                             | HTTP bind address                                       |
| `MCP_PORT`            | `8081`; image: `8080`                 | HTTP listen port                                        |
| `MCP_LOG_LEVEL`       | `INFO`                                | Python and MCP SDK log level                            |
| `MCP_COLLECTIONS`     | `all`                                 | `all` or a JSON list containing `service` and/or `info` |
| `MCP_ENHANCE_QUERY`   | `true`                                | Request query enhancement from Core                     |
| `MCP_RERANK`          | `false`                               | Request reranking from Core                             |
| `MCP_N_RESULTS`       | unset                                 | Optional result limit from 1 to 20                      |
| `MCP_ALLOWED_HOSTS`   | MCP SDK defaults                      | JSON list of accepted HTTP `Host` headers               |
| `MCP_ALLOWED_ORIGINS` | `[]`                                  | JSON list of accepted HTTP `Origin` headers             |

At startup, the effective non-secret configuration is written at info level. This includes the bind address, transport, MCP path, backend URL without credentials or query parameters, retrieval options, and the parsed host and origin allowlists. Check these messages first when a deployment does not use an expected environment value.

## Transport security

Setting `MCP_ALLOWED_HOSTS` enables an explicit allowlist through the MCP SDK's DNS-rebinding protection. Host entries omit the scheme and match exactly, including the port. The only supported wildcard form is `hostname:*`, which accepts any port for that exact hostname; it does not match subdomains.

```dotenv
MCP_ALLOWED_HOSTS=["localhost:*","127.0.0.1:*","dlf-mcp.namespace.svc:*","mcp.example.org","mcp.example.org:*"]
MCP_ALLOWED_ORIGINS=["https://client.example.org"]
```

Requests without an `Origin` header are accepted when their host is valid. If a browser or proxy sends `Origin`, that exact value must be present in `MCP_ALLOWED_ORIGINS`. Origins include the scheme and, when non-default, the port.

| Response                    | Meaning                                                             |
| --------------------------- | ------------------------------------------------------------------- |
| `421 Invalid Host header`   | The received `Host` value is absent from `MCP_ALLOWED_HOSTS`        |
| `403 Invalid Origin header` | The request has an `Origin` value absent from `MCP_ALLOWED_ORIGINS` |

The SDK logs the rejected value. Compare it with the parsed allowlists printed during startup.

## OpenShift

The container listens on port 8080. Configure the Core Service URL and allow every hostname by which clients or routers address the MCP server:

```yaml
env:
  - name: DLF_RETRIEVAL_URL
    value: http://dlf-core:8080/api/retrieval
  - name: MCP_ALLOWED_HOSTS
    value: '["localhost:*","127.0.0.1:*","dlf-mcp","dlf-mcp:*","dlf-mcp.namespace.svc:*","mcp.example.org","mcp.example.org:*"]'
```

OpenShift and Kubernetes HTTP probes normally send the pod IP and port as the `Host` header. Pod IPs are dynamic and should not be added to the allowlist. Send an already allowed host explicitly in both probes:

```yaml
readinessProbe:
  httpGet:
    path: /healthz
    port: http
    httpHeaders:
      - name: Host
        value: localhost:8080
livenessProbe:
  httpGet:
    path: /healthz
    port: http
    httpHeaders:
      - name: Host
        value: localhost:8080
```

After changing environment values, roll out a new pod because settings are read only at process startup. Confirm the effective value in a running deployment with:

```shell
oc exec deployment/dlf-mcp -n namespace -- printenv MCP_ALLOWED_HOSTS
oc logs deployment/dlf-mcp -n namespace | grep -E "Transport security|Invalid Host|Invalid Origin"
```

The server has no client authentication of its own. Protect external Routes with the platform's authentication and authorization controls and use a proxy timeout longer than `DLF_TIMEOUT`.

## Image and releases

`mcp/Dockerfile` builds the OpenShift-compatible image. Tags named `mcp-vX.Y.Z` publish `ghcr.io/it-at-m/dienstleistungsfinder-ki-mcp:X.Y.Z` and `latest`; the release workflow also publishes an immutable `sha-<commit>` tag. Deployments should pin a reviewed version and digest.
