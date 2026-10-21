# Platine image, builds with Podman and Docker. Fully qualified base images: Podman on Fedora
# rejects short names ("python:3.15-slim") without an explicit registry.

# --- Build: dependencies and Platine in /app/.venv ---------------------------------------
# A compiler is needed for the few dependencies without a wheel for this Python yet; it stays here,
# with uv, out of the final image.
FROM docker.io/library/python:3.15-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /bin/

# UV_CACHE_DIR: the build cache mounted below, never a layer of the image.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    UV_CACHE_DIR=/root/.cache/uv

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libc6-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first: this layer only changes when pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY README.md ./
COPY platine ./platine
# Release version, given by CI. Stamped this late so the dependency layer above stays cached.
ARG VERSION=
RUN --mount=type=cache,target=/root/.cache/uv \
    if [ -n "$VERSION" ]; then sed -i "s/^version = \".*\"/version = \"$VERSION\"/" pyproject.toml; fi \
    && uv sync --frozen --no-dev

# --- Runtime -------------------------------------------------------------------------------
FROM docker.io/library/python:3.15-slim

LABEL org.opencontainers.image.title="Platine" \
      org.opencontainers.image.description="Platine: paste a link, get a 320 kbps MP3: YouTube, YouTube Music, SoundCloud, Spotify and hundreds of other sites (yt-dlp + ffmpeg)" \
      org.opencontainers.image.source="https://github.com/BaptGosse/Platine" \
      org.opencontainers.image.url="https://github.com/BaptGosse/Platine" \
      org.opencontainers.image.licenses="MIT"

# Everything written at runtime goes to /tmp: the rest can be read-only.
# The venv is on PATH so yt-dlp finds the `deno` binary installed alongside it.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH" \
    XDG_CACHE_HOME=/tmp/.cache \
    DENO_DIR=/tmp/.cache/deno \
    PLATINE_WORKDIR=/tmp/platine

# The upgrade pulls the Debian security fixes released since the base image was built.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# pip is never used at runtime (uv installs everything) and the libraries it vendors carry CVEs.
RUN python -m pip uninstall --yes --root-user-action=ignore pip

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin app

# Same base image in both stages: the venv's Python links stay valid.
COPY --from=build /app /app
WORKDIR /app

ARG VERSION=
LABEL org.opencontainers.image.version="${VERSION:-dev}"

USER 10001:10001
EXPOSE 8320

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8320/healthz', timeout=4).status == 200 else 1)"]

CMD ["uvicorn", "platine.web:app", "--host", "0.0.0.0", "--port", "8320", "--proxy-headers", "--forwarded-allow-ips=*"]
