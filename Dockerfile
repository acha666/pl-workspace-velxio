# syntax=docker/dockerfile:1
# Workspace and grader images built on one pinned Arduino toolchain stage.
# Every pin is here. VELXIO_BASE_IMAGE is the image built from VELXIO_COMMIT
# (linux/amd64 manifest sha256:10d14c5a3917dcfd0886611a0782d00038e17f462008a33290c69f57ddf9648a,
# created 2026-09-22T02:44Z); upgrade the two together with the patches and
# dependency locks in workspaces/arduino/.
ARG VELXIO_COMMIT=94fd947d6d85afddc7e66c927c7d494e7759f55b
ARG VELXIO_BASE_IMAGE=ghcr.io/davidmonterocrespo24/velxio@sha256:5a9bdeb0edc7ce8c54e5baa6e0e4b8a494e68da72a9e1c50c55e62a67aa9ab35
ARG ARDUINO_AVR_CORE=1.8.6
ARG SIMAVR_COMMIT=d6aed536755bd0ff72b9d2bf02e4a476af64ce82
FROM ${VELXIO_BASE_IMAGE} AS upstream-runtime

# Arduino CLI from the official Velxio image and the AVR core. Both images
# compile with exactly these files.
FROM python:3.12-slim-bookworm AS toolchain
ARG ARDUINO_AVR_CORE
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
    && arduino-cli core install "arduino:avr@${ARDUINO_AVR_CORE}" \
    && rm -rf /opt/arduino/downloads/* \
    && chown -R 1001:1001 /opt/arduino

# ---------------------------------------------------------------------------
# Workspace: Velxio frontend, Python backend and nginx, as in upstream's
# Dockerfile.standalone, built from the pinned commit with the PL patches,
# adapter and dependency locks applied. To build from a local checkout of that
# commit instead, pass --build-context velxio-upstream=PATH (with bake:
# --set '*.contexts.velxio-upstream=PATH').

FROM scratch AS velxio-upstream
ARG VELXIO_COMMIT
ADD https://github.com/davidmonterocrespo24/velxio.git#${VELXIO_COMMIT} /

FROM node:22-bookworm AS velxio-source
WORKDIR /src
COPY --from=velxio-upstream / ./
COPY workspaces/arduino/patches/ /patches/
RUN set -e; for patch in /patches/*.patch; do git apply "$patch"; done
COPY workspaces/arduino/adapter/ ./
COPY workspaces/arduino/dependencies/frontend-package-lock.json frontend/package-lock.json
COPY workspaces/arduino/dependencies/backend-constraints.txt backend/constraints.txt

FROM node:22-bookworm AS frontend
WORKDIR /app
COPY --from=velxio-source /src/frontend/ frontend/
COPY --from=velxio-source /src/scripts/ scripts/
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
COPY --from=velxio-source /src/backend/requirements.txt ./requirements.txt
COPY --from=velxio-source /src/backend/constraints.txt ./constraints.txt
RUN pip install --no-cache-dir -r requirements.txt -c constraints.txt
ENV VELXIO_PL_WORKSPACE=1 \
    VELXIO_NEWS=off \
    ARDUINO_BUILD_CACHE_PATH=/tmp/arduino-cache \
    VELXIO_ARTIFACT_CACHE=/tmp/velxio-artifacts \
    PYTHONDONTWRITEBYTECODE=1
RUN groupadd --gid 1001 student \
    && useradd --uid 1001 --gid 1001 --home-dir /workspace --create-home student
COPY --from=velxio-source /src/backend/app/ /app/app/

FROM backend AS backend-test
RUN pip install --no-cache-dir pytest==8.3.5
COPY --from=velxio-source /src/backend/tests/test_pl_workspace.py /tests/test_pl_workspace.py
ENV PYTHONPATH=/app
RUN python -m pytest -q /tests

# The source offered from the workspace's Help menu: the build files and the
# workspace sources, from which this image rebuilds. Course files and graders,
# whose tests may solve the templates, stay out.
FROM python:3.12-slim-bookworm AS source-offer
WORKDIR /offer
COPY Dockerfile docker-bake.hcl LICENSE SOURCE.md ./
COPY workspaces/ workspaces/
RUN tar -czf /pl-adapter-source.tar.gz .

FROM backend AS workspace
COPY --from=frontend-builder /app/frontend/dist/ /usr/share/nginx/html/
COPY --from=source-offer /pl-adapter-source.tar.gz /usr/share/nginx/html/pl-adapter-source.tar.gz
COPY workspaces/arduino/nginx.conf /app/pl-nginx.conf
COPY --chmod=755 workspaces/arduino/entrypoint.sh /app/pl-entrypoint.sh
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
# Arduino grader: avrsim (simavr) and the arduinograder package, installed from
# the uv workspace lock.

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
COPY graders/arduino/avrsim/avrsim.c avrsim.c
RUN gcc -O2 -Wall -Wextra -Werror -o /usr/local/bin/avrsim avrsim.c \
        -I simavr/simavr/sim simavr/simavr/obj-*/libsimavr.a -lelf

FROM toolchain AS grader
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends libelf1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1002 sbuser \
    && useradd --uid 1002 --gid 1002 --no-create-home --home-dir /nonexistent sbuser
COPY --from=simavr /usr/local/bin/avrsim /usr/local/bin/avrsim
# The package and its dependencies go into one environment outside the source
# tree; dependencies are installed before the source so they cache separately.
ENV UV_PROJECT_ENVIRONMENT=/opt/arduinograder \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1 \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /src
COPY pyproject.toml uv.lock ./
COPY graders/arduino/pyproject.toml graders/arduino/README.md graders/arduino/
RUN uv sync --frozen --no-dev --package arduinograder --no-install-workspace
COPY graders/arduino/src/ graders/arduino/src/
RUN uv sync --frozen --no-dev --package arduinograder --no-editable
ENV PATH=/opt/arduinograder/bin:/usr/local/bin:/usr/bin:/bin \
    PYTHONPATH=/grade/serverFilesCourse \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
LABEL org.opencontainers.image.title="PrairieLearn Arduino grader" \
      org.opencontainers.image.licenses="AGPL-3.0-only"
WORKDIR /grade
ENTRYPOINT ["python3", "-m", "arduinograder"]

FROM grader AS grader-test
WORKDIR /src
RUN uv sync --frozen --package arduinograder --no-editable
COPY graders/arduino/tests/ graders/arduino/tests/
COPY course/ course/
WORKDIR /src/graders/arduino
RUN uv run --frozen --no-sync ruff check . \
    && uv run --frozen --no-sync ruff format --check . \
    && uv run --frozen --no-sync mypy \
    && uv run --frozen --no-sync pytest -q
