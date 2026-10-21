"""HTTP API and web interface."""

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import mimetypes
import os
import secrets
import tempfile
import zipfile
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import Gauge
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel
from starlette.background import BackgroundTask
from yt_dlp.utils import sanitize_filename

from . import errors, sources
from .config import settings
from .jobs import Job, JobManager, Status

log = logging.getLogger("platine")
manager = JobManager()

STATIC_DIR = Path(__file__).parent / "static"
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".mjs")

# Probes and Prometheus scraping never go through authentication.
PUBLIC_PATHS = {"/healthz", "/metrics"}
PURGE_INTERVAL = 60.0


async def _purge_regularly() -> None:
    while True:
        await asyncio.sleep(PURGE_INTERVAL)
        await run_in_threadpool(manager.purge)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Cleans leftovers at startup, purges expired jobs while running, stops conversions on exit."""
    JobManager.clean_leftovers()
    purger = asyncio.create_task(_purge_regularly())
    yield
    purger.cancel()
    manager.shutdown()


app = FastAPI(title="Platine", lifespan=lifespan, docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")

Instrumentator(excluded_handlers=list(PUBLIC_PATHS)).instrument(app).expose(app, include_in_schema=False)
Gauge("platine_jobs_active", "Conversions waiting or running.").set_function(manager.active_count)


def _authorized(header: str | None, expected_password: str) -> bool:
    scheme, _, encoded = (header or "").partition(" ")
    if scheme.lower() != "basic":
        return False
    try:
        username, _, password = base64.b64decode(encoded, validate=True).decode().partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return False
    username_ok = secrets.compare_digest(username.encode(), settings.auth_username.encode())
    password_ok = secrets.compare_digest(password.encode(), expected_password.encode())
    return username_ok and password_ok


@app.middleware("http")
async def basic_auth(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """Requires the configured password on every route except the probes."""
    public = request.url.path in PUBLIC_PATHS
    password = settings.auth_password
    if password and not public and not _authorized(request.headers.get("authorization"), password):
        return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Platine", charset="UTF-8"'})
    return await call_next(request)


def problem(status_code: int, code: str, message: str) -> HTTPException:
    """Error response with a stable code that the interface translates, and an English message."""
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


class ErrorOut(BaseModel):
    """Why a conversion failed."""

    code: str
    message: str


class JobOut(BaseModel):
    """A conversion as seen by the interface."""

    id: str
    url: str
    source: str
    title: str | None
    artist: str | None
    album: str | None
    duration: float | None
    thumbnail: str | None
    status: Status
    progress: float | None
    speed: float | None
    eta: int | None
    error: ErrorOut | None
    filename: str | None
    size: int | None
    expires_at: float | None

    @classmethod
    def of(cls, job: Job) -> "JobOut":
        """Snapshot of `job` for the API."""
        t = job.track
        file = job.file if job.status is Status.DONE else None
        return cls(
            id=job.id,
            url=t.url,
            source=t.source,
            title=t.title,
            artist=t.artist,
            album=t.album,
            duration=t.duration,
            thumbnail=t.thumbnail,
            status=job.status,
            progress=job.progress,
            speed=job.speed,
            eta=job.eta,
            error=ErrorOut(code=job.error.code, message=job.error.message) if job.error else None,
            filename=file.name if file else None,
            size=file.stat().st_size if file and file.exists() else None,
            expires_at=job.expires_at,
        )


class NewJobs(BaseModel):
    """Request body: the link to convert."""

    url: str


class CreatedJobs(BaseModel):
    """Jobs created for a link, with the playlist or album name when there is one."""

    playlist: str | None
    jobs: list[JobOut]


def _parse_ids(ids: str) -> list[Job]:
    return [job for job_id in ids.split(",") if (job := manager.get(job_id))]


@app.post("/api/jobs", status_code=201)
def create_jobs(body: NewJobs) -> CreatedJobs:
    """Reads a link and queues one conversion per track it contains."""
    try:
        resolved = sources.resolve(body.url)
    except Exception as exc:
        if not errors.is_expected(exc):
            log.exception("Unexpected failure while reading %s", body.url)
        explained = errors.explain(exc)
        raise problem(400, explained.code, explained.message) from exc
    if not resolved.tracks:
        raise problem(400, "no_tracks", "No tracks found at this address.")
    if manager.active_count() + len(resolved.tracks) > settings.max_queued:
        raise problem(429, "queue_full", "Too many conversions are waiting: try again in a few minutes.")
    jobs = [manager.submit(track) for track in resolved.tracks]
    return CreatedJobs(playlist=resolved.playlist, jobs=[JobOut.of(job) for job in jobs])


@app.get("/api/jobs")
def list_jobs(ids: str = "") -> list[JobOut]:
    """State of the requested conversions; expired ones are left out."""
    return [JobOut.of(job) for job in _parse_ids(ids)]


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> JobOut:
    """Stops a conversion."""
    job = manager.cancel(job_id)
    if job is None:
        raise problem(404, "job_not_found", "Conversion not found.")
    return JobOut.of(job)


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str) -> None:
    """Forgets a conversion and deletes its file."""
    manager.remove(job_id)


@app.get("/api/jobs/{job_id}/file")
def job_file(job_id: str) -> FileResponse:
    """Downloads the finished MP3."""
    job = manager.get(job_id)
    if job is None or job.status is not Status.DONE or job.file is None or not job.file.exists():
        raise problem(404, "file_gone", "This file is no longer available: start the conversion again.")
    return FileResponse(job.file, media_type="audio/mpeg", filename=job.file.name)


@app.get("/api/archive")
def archive(ids: str, name: str = "Platine") -> FileResponse:
    """Every finished MP3 among `ids`, in a zip (stored as is: MP3 is already compressed)."""
    files = [job.file for job in _parse_ids(ids) if job.status is Status.DONE and job.file and job.file.exists()]
    if not files:
        raise problem(404, "archive_empty", "No finished file to put in the archive.")
    fd, path = tempfile.mkstemp(prefix="archive-", suffix=".zip", dir=settings.workdir)
    os.close(fd)
    used: set[str] = set()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_STORED) as zf:
        for file in files:
            arcname, n = file.name, 1
            while arcname in used:
                n += 1
                arcname = f"{file.stem} ({n}){file.suffix}"
            used.add(arcname)
            zf.write(file, arcname)
    return FileResponse(
        path,
        media_type="application/zip",
        filename=f"{sanitize_filename(name) or 'Platine'}.zip",
        background=BackgroundTask(os.unlink, path),
    )


@app.get("/api/config")
def client_config() -> dict[str, int]:
    """Server settings the interface needs."""
    return {"file_ttl": settings.file_ttl, "max_playlist_items": settings.max_playlist_items}


def _precache_manifest() -> list[dict[str, str]]:
    """Interface files to cache for offline use, each with a fingerprint of its content."""
    entries = []
    for path in sorted(STATIC_DIR.rglob("*")):
        relative = path.relative_to(STATIC_DIR).as_posix()
        unused = path.suffix in {".map", ".md", ".txt", ".woff"} or path.name.startswith(
            ("LICENSE", "logo", "screenshot-")
        )
        if path.is_dir() or relative == "sw.js" or unused:
            continue
        revision = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
        entries.append({"url": "/" if relative == "index.html" else f"/{relative}", "revision": revision})
    return entries


@app.get("/dmca", include_in_schema=False)
def legal_page() -> FileResponse:
    """DMCA and legal notice: the interface shows it instead of the converter on this path."""
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/sw.js", include_in_schema=False)
def service_worker() -> Response:
    """Service worker script, prefixed with the list of files to precache."""
    script = f"const PRECACHE = {json.dumps(_precache_manifest())};\n" + (STATIC_DIR / "sw.js").read_text()
    return Response(script, media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness and readiness probe."""
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
