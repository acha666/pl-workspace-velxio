# Workspace and grader images built on one pinned Arduino toolchain stage.
# Pins must match toolchain.lock.json; scripts/prepare.py checks them.
ARG VELXIO_BASE_IMAGE=ghcr.io/davidmonterocrespo24/velxio@sha256:5a9bdeb0edc7ce8c54e5baa6e0e4b8a494e68da72a9e1c50c55e62a67aa9ab35
ARG SIMAVR_COMMIT=d6aed536755bd0ff72b9d2bf02e4a476af64ce82
FROM ${VELXIO_BASE_IMAGE} AS upstream-runtime

# Arduino CLI from the official Velxio image and the AVR core. Both images
# compile with exactly these files.
FROM python:3.12-slim-bookworm AS toolchain
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=upstream-runtime /usr/local/bin/arduino-cli /usr/local/bin/arduino-cli
ENV ARDUINO_DIRECTORIES_DATA=/opt/arduino/data \
    ARDUINO_DIRECTORIES_DOWNLOADS=/opt/arduino/downloads \
    ARDUINO_DIRECTORIES_USER=/opt/arduino/user \
    ARDUINO_UPDATER_ENABLE_NOTIFICATION=false \
    ARDUINO_METRICS_ENABLED=false
RUN mkdir -p /opt/arduino/user \
    && arduino-cli core update-index \
    && arduino-cli core install arduino:avr@1.8.6 \
    && rm -rf /opt/arduino/downloads/* \
    && chown -R 1001:1001 /opt/arduino

# ---------------------------------------------------------------------------
# Workspace: Velxio frontend, Python backend and nginx, as in upstream's
# Dockerfile.standalone. Requires the context prepared by scripts/prepare.py.

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
FROM toolchain AS backend
RUN apt-get update && apt-get install -y --no-install-recommends curl nginx \
    && rm -rf /var/lib/apt/lists/* /etc/nginx/sites-enabled/default
WORKDIR /app
COPY upstream/backend/requirements.txt ./requirements.txt
COPY upstream/backend/constraints.txt ./constraints.txt
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt
ENV VELXIO_PL_WORKSPACE=1 \
    VELXIO_NEWS=off \
    ARDUINO_BUILD_CACHE_PATH=/tmp/arduino-cache \
    VELXIO_ARTIFACT_CACHE=/tmp/velxio-artifacts \
    PYTHONDONTWRITEBYTECODE=1
RUN groupadd --gid 1001 student \
    && useradd --uid 1001 --gid 1001 --home-dir /workspace --create-home student
COPY upstream/backend/app/ /app/app/

FROM backend AS backend-test
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pytest==8.3.5
COPY scripts/prepare.py /scripts/prepare.py
COPY upstream/backend/tests/test_pl_workspace.py /tests/test_pl_workspace.py
COPY tests/ /tests/
COPY course/ /course/
ENV PYTHONPATH=/app
RUN python -m pytest -q /tests

FROM backend AS workspace
COPY --from=frontend-builder /app/frontend/dist/ /usr/share/nginx/html/
COPY pl-adapter-source.tar.gz /usr/share/nginx/html/pl-adapter-source.tar.gz
COPY workspace/nginx.conf /app/pl-nginx.conf
COPY --chmod=755 workspace/entrypoint.sh /app/pl-entrypoint.sh
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

# ---------------------------------------------------------------------------
# Grader: avrsim (simavr) and the arduinograder Python package. Builds from the
# repository root or the prepared context.

FROM python:3.12-slim-bookworm AS simavr
ARG SIMAVR_COMMIT
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential ca-certificates git libelf-dev pkg-config \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN git init --quiet simavr \
    && git -C simavr fetch --quiet --depth 1 https://github.com/buserror/simavr.git "$SIMAVR_COMMIT" \
    && git -C simavr checkout --quiet --detach FETCH_HEAD \
    && make -C simavr/simavr RELEASE=1 libsimavr
COPY grader/avrsim/avrsim.c avrsim.c
RUN gcc -O2 -Wall -Wextra -Werror -o /usr/local/bin/avrsim avrsim.c \
        -I simavr/simavr/sim simavr/simavr/obj-*/libsimavr.a -lelf

FROM toolchain AS grader
RUN apt-get update && apt-get install -y --no-install-recommends libelf1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1002 sbuser \
    && useradd --uid 1002 --gid 1002 --no-create-home --home-dir /nonexistent sbuser
COPY grader/requirements.txt /opt/arduinograder/requirements.txt
RUN pip install --no-cache-dir -r /opt/arduinograder/requirements.txt
COPY --from=simavr /usr/local/bin/avrsim /usr/local/bin/avrsim
COPY grader/arduinograder/ /opt/arduinograder/arduinograder/
ENV PYTHONPATH=/opt/arduinograder:/grade/serverFilesCourse \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
LABEL org.opencontainers.image.title="PrairieLearn Arduino grader" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
WORKDIR /grade
ENTRYPOINT ["python3", "/grade/tests/test.py"]

FROM grader AS grader-test
RUN pip install --no-cache-dir pytest==8.3.5
COPY grader/tests/ /opt/arduinograder/tests/
COPY course/ /opt/course/
RUN python -m pytest -q -p no:cacheprovider /opt/arduinograder/tests
