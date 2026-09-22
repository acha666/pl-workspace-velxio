# Arduino target derived from the pinned official Dockerfile.standalone.
ARG VELXIO_BASE_IMAGE=ghcr.io/davidmonterocrespo24/velxio@sha256:5a9bdeb0edc7ce8c54e5baa6e0e4b8a494e68da72a9e1c50c55e62a67aa9ab35
FROM ${VELXIO_BASE_IMAGE} AS upstream-runtime

FROM node:22-bookworm AS frontend
WORKDIR /app
COPY upstream/frontend/ frontend/
COPY upstream/scripts/ scripts/
WORKDIR /app/frontend
RUN npm ci --include=optional
ENV VITE_PL_WORKSPACE=true

FROM frontend AS frontend-test
RUN npm test -- src/pl

FROM frontend AS frontend-builder
RUN npm run generate:component-svgs && npx --no-install vite build
RUN rm -rf dist/examples-thumbs dist/marketing dist/firmware \
    && rm -f dist/sitemap.xml dist/robots.txt dist/llms.txt dist/component-svgs/test.html

# Same Python/nginx runtime as upstream; omit ESP-IDF, QEMU and chip compilers.
FROM python:3.12-slim-bookworm AS backend
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl nginx \
    && rm -rf /var/lib/apt/lists/* /etc/nginx/sites-enabled/default
COPY --from=upstream-runtime /usr/local/bin/arduino-cli /usr/local/bin/arduino-cli
WORKDIR /app
COPY upstream/backend/requirements.txt ./requirements.txt
COPY upstream/backend/constraints.txt ./constraints.txt
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt
ENV VELXIO_PL_WORKSPACE=1 \
    VELXIO_NEWS=off \
    ARDUINO_DIRECTORIES_DATA=/opt/arduino/data \
    ARDUINO_DIRECTORIES_DOWNLOADS=/opt/arduino/downloads \
    ARDUINO_DIRECTORIES_USER=/opt/arduino/user \
    ARDUINO_BUILD_CACHE_PATH=/tmp/arduino-cache \
    ARDUINO_UPDATER_ENABLE_NOTIFICATION=false \
    ARDUINO_METRICS_ENABLED=false \
    VELXIO_ARTIFACT_CACHE=/tmp/velxio-artifacts \
    PYTHONDONTWRITEBYTECODE=1
RUN groupadd --gid 1001 student \
    && useradd --uid 1001 --gid 1001 --home-dir /workspace --create-home student \
    && mkdir -p /opt/arduino/user \
    && arduino-cli core update-index \
    && arduino-cli core install arduino:avr@1.8.6 \
    && rm -rf /opt/arduino/downloads/* \
    && chown -R 1001:1001 /opt/arduino /workspace
COPY upstream/backend/app/ /app/app/

FROM backend AS backend-test
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pytest==8.3.5
COPY scripts/prepare.py /scripts/prepare.py
COPY upstream/backend/tests/test_pl_workspace.py /tests/test_pl_workspace.py
COPY tests/ /tests/
COPY templates/ /templates/
ENV PYTHONPATH=/app
RUN python -m pytest -q /tests

FROM backend AS arduino
COPY --from=frontend-builder /app/frontend/dist/ /usr/share/nginx/html/
COPY pl-adapter-source.tar.gz /usr/share/nginx/html/pl-adapter-source.tar.gz
COPY docker/nginx.conf /app/pl-nginx.conf
COPY --chmod=755 docker/entrypoint.sh /app/pl-entrypoint.sh
LABEL com.prairielearn.workspace.port="8080" \
      com.prairielearn.workspace.home="/workspace" \
      com.prairielearn.workspace.rewrite-url="true" \
      org.opencontainers.image.title="PrairieLearn Velxio Arduino workspace" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD curl -fsS http://127.0.0.1:8080/health || exit 1
USER 1001:1001
WORKDIR /app
ENTRYPOINT ["/app/pl-entrypoint.sh"]
