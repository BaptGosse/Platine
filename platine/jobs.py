"""In-memory conversion queue (one app instance at a time)."""

import logging
import secrets
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

from prometheus_client import Counter, Histogram

from . import errors
from .config import settings
from .downloader import Cancelled, download_mp3
from .models import Track

log = logging.getLogger("platine.jobs")

JOB_DIR_PREFIX = "job-"

CONVERSIONS = Counter("platine_conversions", "Finished conversions, by result and by site.", ["status", "source"])
CONVERSION_SECONDS = Histogram(
    "platine_conversion_duration_seconds",
    "Duration of a successful conversion, download included.",
    buckets=(2, 5, 10, 20, 30, 60, 120, 300, 600),
)


class Status(StrEnum):
    """Stage of a conversion, as shown in the interface."""

    QUEUED = "queued"
    MATCHING = "matching"
    """Spotify track: looking for the same track on YouTube Music."""
    DOWNLOADING = "downloading"
    CONVERTING = "converting"
    DONE = "done"
    ERROR = "error"
    CANCELLED = "cancelled"


FINISHED = {Status.DONE, Status.ERROR, Status.CANCELLED}


@dataclass
class Job:
    """One track to convert, and where its conversion stands."""

    track: Track
    id: str = field(default_factory=lambda: secrets.token_urlsafe(9))
    status: Status = Status.QUEUED
    progress: float | None = None
    speed: float | None = None
    eta: int | None = None
    error: errors.Problem | None = None
    file: Path | None = None
    finished_at: float | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def workdir(self) -> Path:
        """Folder holding the downloads and the finished MP3 of this job."""
        return settings.workdir / f"{JOB_DIR_PREFIX}{self.id}"

    @property
    def expires_at(self) -> float | None:
        """When the finished file gets deleted (Unix time), once the job is over."""
        return self.finished_at + settings.file_ttl if self.finished_at else None


class JobManager:
    """Runs conversions in a thread pool and keeps their state in memory."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=settings.max_concurrent, thread_name_prefix="platine")

    def submit(self, track: Track) -> Job:
        """Queues a conversion of `track` and returns its job right away."""
        job = Job(track)
        with self._lock:
            self._jobs[job.id] = job
        self._pool.submit(self._run, job)
        return job

    def get(self, job_id: str) -> Job | None:
        """The job with this id, if the server still knows it."""
        return self._jobs.get(job_id)

    def active_count(self) -> int:
        """Number of conversions waiting or running."""
        return sum(1 for job in list(self._jobs.values()) if job.status not in FINISHED)

    def cancel(self, job_id: str) -> Job | None:
        """Asks a job to stop; a job that has not started yet is cancelled at once."""
        job = self.get(job_id)
        if job and job.status not in FINISHED:
            job.cancel_event.set()
            if job.status is Status.QUEUED:
                self._finish(job, Status.CANCELLED)
        return job

    def remove(self, job_id: str) -> None:
        """Cancels a job if needed, forgets it and deletes its files."""
        job = self.cancel(job_id)
        with self._lock:
            self._jobs.pop(job_id, None)
        # A running conversion cleans up its own folder when it notices the cancellation.
        if job and job.status in FINISHED:
            shutil.rmtree(job.workdir, ignore_errors=True)

    def purge(self) -> None:
        """Forgets conversions finished more than `file_ttl` seconds ago and deletes their files."""
        now = time.time()
        with self._lock:
            expired = [j for j in self._jobs.values() if j.expires_at and j.expires_at < now]
            for job in expired:
                del self._jobs[job.id]
        for job in expired:
            shutil.rmtree(job.workdir, ignore_errors=True)

    def shutdown(self) -> None:
        """Stops every conversion, when the server shuts down."""
        for job in list(self._jobs.values()):
            job.cancel_event.set()
        self._pool.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def clean_leftovers() -> None:
        """Deletes work folders left behind by a previous run (hard stop)."""
        settings.workdir.mkdir(parents=True, exist_ok=True)
        for leftover in settings.workdir.glob(f"{JOB_DIR_PREFIX}*"):
            shutil.rmtree(leftover, ignore_errors=True)
        for archive in settings.workdir.glob("archive-*.zip"):
            archive.unlink(missing_ok=True)

    def _finish(self, job: Job, status: Status) -> None:
        if job.status in FINISHED:
            return
        job.status = status
        job.finished_at = time.time()
        job.speed = job.eta = None
        if status is Status.DONE:
            job.progress = 1.0
        CONVERSIONS.labels(status=status.value, source=job.track.source).inc()

    def _run(self, job: Job) -> None:
        if job.cancel_event.is_set():
            return

        def on_progress(
            stage: str, fraction: float | None = None, speed: float | None = None, eta: int | None = None
        ) -> None:
            status = Status(stage)
            if status is job.status and fraction is not None and job.progress is not None:
                fraction = max(fraction, job.progress)  # size estimates sometimes move the bar backwards
            job.status, job.progress, job.speed, job.eta = status, fraction, speed, eta

        def on_meta(fields: dict[str, Any]) -> None:
            for name, value in fields.items():
                if value:
                    setattr(job.track, name, value)

        started = time.monotonic()
        try:
            job.file = download_mp3(
                job.track, job.workdir, on_progress=on_progress, on_meta=on_meta, cancel=job.cancel_event
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught  # a failure ends this job, never the worker
            shutil.rmtree(job.workdir, ignore_errors=True)
            if job.cancel_event.is_set() or isinstance(exc, Cancelled):
                self._finish(job, Status.CANCELLED)
                return
            if not errors.is_expected(exc):
                log.exception("Unexpected failure for %s", job.track.url)
            job.error = errors.explain(exc)
            self._finish(job, Status.ERROR)
        else:
            self._finish(job, Status.DONE)
            CONVERSION_SECONDS.observe(time.monotonic() - started)
        finally:
            job.track.info = None  # the yt-dlp dict is heavy and no longer needed
