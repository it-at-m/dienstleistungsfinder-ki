FROM registry.access.redhat.com/ubi10/nodejs-24:latest@sha256:80c87fe2b161979a961911c837efff1198bdd597c6dbe7d2e59bf1c60638188d AS frontend
WORKDIR /build
COPY frontend/ .
USER root
RUN mkdir -p /build/dist/assets \
    && curl -fSL "https://assets.muenchen.de/mde/1.1.19/css/style.css" -o /build/dist/assets/mde-style.css \
    && chown -R 1001:0 /build && chmod -R g+rwX /build
USER 1001
RUN npm ci && npm run build

FROM registry.access.redhat.com/ubi10/ubi-minimal:latest@sha256:204e1531cee54562b107fb31e0b327062fc3d5d67af7cc0d2e66b2c572b9044f
WORKDIR /app
ARG UV_HTTP_TIMEOUT=300
ARG UV_HTTP_RETRIES=10
COPY --from=ghcr.io/astral-sh/uv:latest@sha256:61d393e44e249f2e4b526b6c7ddcecce245946826e608e11c93ad4f5bba55b21 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=0 UV_LINK_MODE=copy
COPY backend/pyproject.toml backend/.python-version backend/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev --locked --no-install-project
COPY backend/ .
COPY --from=frontend /build/dist/ static
RUN --mount=type=cache,target=/root/.cache/uv uv sync --no-dev --locked
ARG IMAGE_CREATED="unknown"
ARG IMAGE_REVISION="unknown"
ARG IMAGE_VERSION="unknown"
LABEL org.opencontainers.image.authors='Landeshauptstadt München <opensource@muenchen.de>' \
      org.opencontainers.image.vendor='Landeshauptstadt München' \
      org.opencontainers.image.created="$IMAGE_CREATED" \
      org.opencontainers.image.revision="$IMAGE_REVISION" \
      org.opencontainers.image.version="$IMAGE_VERSION" \
      org.opencontainers.image.url='https://github.com/it-at-m/Dienstleistungsfinder-KI' \
      org.opencontainers.image.documentation='https://github.com/it-at-m/Dienstleistungsfinder-KI#readme' \
      org.opencontainers.image.source='https://github.com/it-at-m/Dienstleistungsfinder-KI' \
      org.opencontainers.image.licenses='MIT' \
      org.opencontainers.image.title='dienstleistungsfinder-ki-core'
USER root
RUN chgrp -R 0 /app && chmod -R g+rwX /app
USER 1001
ENV PATH="/app/.venv/bin:$PATH" TQDM_DISABLE=1 HF_HUB_DISABLE_PROGRESS_BARS=1 PYTHONWARNINGS="ignore" APP_VERSION=${IMAGE_VERSION}
EXPOSE 8080
ENTRYPOINT ["python", "app.py"]
