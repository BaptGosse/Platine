import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from yt_dlp.utils import DownloadError

from platine import jobs
from platine.config import settings
from platine.downloader import Cancelled
from platine.errors import UserError
from platine.jobs import FINISHED, Job, JobManager, Status
from platine.models import Track
from tests.conftest import wait_for

FakeDownload = Callable[..., Path]


def track(n: int = 1) -> Track:
    return Track(url=f"https://www.youtube.com/watch?v={n}", source="YouTube", title=f"Track {n}", info={"id": n})


def writes_mp3(track: Track, dest: Path, *, on_progress: Any, on_meta: Any, cancel: threading.Event) -> Path:
    on_meta({"artist": "Artist", "title": None})
    on_progress("downloading", 0.5, 1000.0, 3)
    on_progress("downloading", 0.4, 1000.0, 3)  # lower estimate: the bar must not move back
    on_progress("converting")
    dest.mkdir(parents=True, exist_ok=True)
    mp3 = dest / "Artist - Track.mp3"
    mp3.write_bytes(b"mp3")
    return mp3


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[FakeDownload], JobManager]]:
    created: list[JobManager] = []

    def make(fake: FakeDownload) -> JobManager:
        monkeypatch.setattr(jobs, "download_mp3", fake)
        created.append(JobManager())
        return created[-1]

    yield make
    for m in created:
        m.shutdown()


def finished(job: Job) -> Callable[[], bool]:
    return lambda: job.status in FINISHED


def test_successful_conversion(manager: Callable[[FakeDownload], JobManager]) -> None:
    progress_seen: list[float | None] = []
    submitted: list[Job] = []
    ready = threading.Event()

    def spy(track: Track, dest: Path, *, on_progress: Any, **kwargs: Any) -> Path:
        ready.wait(5)  # wait until the test holds the job

        def record(stage: str, *args: Any) -> None:
            on_progress(stage, *args)
            progress_seen.append(submitted[0].progress)

        return writes_mp3(track, dest, on_progress=record, **kwargs)

    m = manager(spy)
    job = m.submit(track())
    submitted.append(job)
    ready.set()
    wait_for(finished(job))
    assert job.status is Status.DONE
    assert job.progress == 1.0
    assert progress_seen[:2] == [0.5, 0.5]
    assert job.file is not None and job.file.read_bytes() == b"mp3"
    assert job.track.artist == "Artist" and job.track.title == "Track 1"  # empty values overwrite nothing
    assert job.track.info is None  # released after the conversion
    assert job.expires_at == pytest.approx(time.time() + settings.file_ttl, abs=5)
    assert m.active_count() == 0


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (UserError("ytm_no_match", "Track not found on YouTube Music."), "ytm_no_match"),
        (DownloadError("ERROR: Private video"), "private"),
    ],
)
def test_failed_conversion_keeps_a_readable_error_and_cleans_up(
    manager: Callable[[FakeDownload], JobManager], error: Exception, code: str
) -> None:
    def fails(track: Track, dest: Path, **kwargs: Any) -> Path:
        dest.mkdir(parents=True)
        (dest / "partial.webm").write_bytes(b"x")
        raise error

    job = manager(fails).submit(track())
    wait_for(finished(job))
    assert job.status is Status.ERROR
    assert job.error is not None and job.error.code == code and job.error.message
    assert not job.workdir.exists()


def test_unexpected_bug_is_logged_with_its_traceback(
    manager: Callable[[FakeDownload], JobManager], caplog: pytest.LogCaptureFixture
) -> None:
    def crashes(track: Track, dest: Path, **kwargs: Any) -> Path:
        raise KeyError("requested_downloads")

    job = manager(crashes).submit(track())
    wait_for(finished(job))
    assert job.error is not None and job.error.code == "unexpected"
    assert "Unexpected failure" in caplog.text


def blocks_until_cancelled(started: threading.Event) -> FakeDownload:
    def download(track: Track, dest: Path, *, on_progress: Any, cancel: threading.Event, **kwargs: Any) -> Path:
        on_progress("downloading", 0.1)
        started.set()
        cancel.wait(5)
        raise Cancelled

    return download


def test_cancel_a_running_conversion(manager: Callable[[FakeDownload], JobManager]) -> None:
    started = threading.Event()
    m = manager(blocks_until_cancelled(started))
    job = m.submit(track())
    started.wait(5)
    assert m.active_count() == 1
    m.cancel(job.id)
    wait_for(finished(job))
    assert job.status is Status.CANCELLED


def test_cancel_a_queued_conversion_without_running_it(
    manager: Callable[[FakeDownload], JobManager], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "max_concurrent", 1)
    started = threading.Event()
    m = manager(blocks_until_cancelled(started))
    first, queued = m.submit(track(1)), m.submit(track(2))
    started.wait(5)
    assert queued.status is Status.QUEUED
    m.cancel(queued.id)
    assert queued.status is Status.CANCELLED
    m.cancel(first.id)
    wait_for(finished(first))
    assert queued.status is Status.CANCELLED  # never started


def test_remove_forgets_the_job_and_deletes_its_file(manager: Callable[[FakeDownload], JobManager]) -> None:
    m = manager(writes_mp3)
    job = m.submit(track())
    wait_for(finished(job))
    m.remove(job.id)
    assert m.get(job.id) is None
    assert not job.workdir.exists()
    m.remove("unknown")  # no effect


def test_purge_only_drops_expired_jobs(manager: Callable[[FakeDownload], JobManager]) -> None:
    m = manager(writes_mp3)
    old, recent = m.submit(track(1)), m.submit(track(2))
    wait_for(lambda: old.status in FINISHED and recent.status in FINISHED)
    assert old.finished_at is not None
    old.finished_at -= settings.file_ttl + 1
    m.purge()
    assert m.get(old.id) is None and not old.workdir.exists()
    assert m.get(recent.id) is recent


def test_clean_leftovers_only_touches_our_own_files() -> None:
    settings.workdir.mkdir(parents=True)
    (settings.workdir / "job-old").mkdir()
    (settings.workdir / "archive-old.zip").write_bytes(b"")
    (settings.workdir / "notes.txt").write_text("keep me")
    JobManager.clean_leftovers()
    assert [p.name for p in settings.workdir.iterdir()] == ["notes.txt"]
