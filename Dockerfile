# Platine image, builds with Podman and Docker. Fully qualified base image: Podman on Fedora
# rejects short names ("python:3.14-slim") without an explicit registry.
FROM docker.io/library/python:3.14-slim

LABEL org.opencontainers.image.title="Platine" \
      org.opencontainers.image.description="Paste a link, get a 320 kbps MP3: YouTube, YouTube Music, SoundCloud, Spotify and hundreds of other sites (yt-dlp + ffmpeg)" \
      org.opencontainers.image.source="https://github.com/BaptGosse/Platine" \
      org.opencontainers.image.url="https://github.com/BaptGosse/Platine" \
      org.opencontainers.image.version="2.0.0" \
      org.opencontainers.image.licenses="MIT"

COPY --from=ghcr.io/astral-sh/uv:0.13.3 /uv /uvx /bin/

# Everything written at runtime goes to /tmp: the rest can be read-only.
# The venv is on PATH so yt-dlp finds the `deno` binary installed alongside it.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    XDG_CACHE_HOME=/tmp/.cache \
    DENO_DIR=/tmp/.cache/deno \
    PLATINE_WORKDIR=/tmp/platine

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /tmp --shell /usr/sbin/nologin app

WORKDIR /app

# Dependencies first: this layer only changes when pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY README.md ./
COPY platine ./platine
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

USER 10001:10001
EXPOSE 8320

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8320/healthz', timeout=4).status == 200 else 1)"]

CMD ["uvicorn", "platine.web:app", "--host", "0.0.0.0", "--port", "8320", "--proxy-headers", "--forwarded-allow-ips=*"]
