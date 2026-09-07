FROM registry.access.redhat.com/ubi10/ubi-minimal:latest@sha256:5a1acbfad56de537f978184e662a02ba8141d82a3ce0d2aca183bfad812b0ea7 AS build
WORKDIR /app
ARG UV_HTTP_TIMEOUT=300
ARG UV_HTTP_RETRIES=10
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:440fd6477af86a2f1b38080c539f1672cd22acb1b1a47e321dba5158ab08864d /uv /uvx /bin/
# Keep managed Python outside /root so OpenShift's assigned UID can execute it.
ENV UV_COMPILE_BYTECODE=0 UV_LINK_MODE=copy UV_PYTHON_INSTALL_DIR=/opt/python
COPY pyproject.toml .python-version uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev --locked --no-install-project
COPY README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev --locked --no-editable
RUN chmod -R a+rX /opt/python /app/.venv

FROM registry.access.redhat.com/ubi10/ubi-minimal:latest@sha256:5a1acbfad56de537f978184e662a02ba8141d82a3ce0d2aca183bfad812b0ea7
WORKDIR /app
COPY --from=build /opt/python /opt/python
COPY --from=build /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MCP_HOST=0.0.0.0 \
    MCP_PORT=8080
LABEL org.opencontainers.image.title="dienstleistungsfinder-ki-mcp" \
      org.opencontainers.image.source="https://github.com/it-at-m/Dienstleistungsfinder-KI" \
      org.opencontainers.image.licenses="MIT"
# OpenShift assigns an arbitrary UID; all runtime files are readable/executable.
USER 1001:0
EXPOSE 8080
ENTRYPOINT ["dlf-search-mcp"]
