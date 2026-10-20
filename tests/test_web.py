import base64
import io
import json
import threading
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from platine import jobs, web
from platine.config import settings
from platine.errors import UserError
from platine.jobs import JobManager
from platine.models import Resolved, Track
from tests.conftest import wait_for

TRACKS = {
    "https://www.youtube.com/watch?v=1": Resolved(
        [Track(url="https://www.youtube.com/watch?v=1", source="YouTube", title="One")]
    ),
    "https://soundcloud.com/a/sets/b": Resolved(
        [Track(url=f"https://soundcloud.com/a/{n}", source="SoundCloud", title=n) for n in ("two", "three", "two")],
        playlist="My set",
    ),
    "https://example.com/empty": Resolved([]),
}


def fake_resolve(url: str) -> Resolved:
    if url == "https://example.com/bug":
        raise RuntimeError("boom")
    if url not in TRACKS:
        raise UserError("unsupported_site", "This site is not supported.")
    return TRACKS[url]


def fake_download(track: Track, dest: Path, **kwargs: Any) -> Path:
    dest.mkdir(parents=True, exist_ok=True)
    mp3 = dest / f"{track.title}.mp3"
    mp3.write_bytes(track.url.encode())
    return mp3


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(web.sources, "resolve", fake_resolve)
    monkeypatch.setattr(jobs, "download_mp3", fake_download)
    monkeypatch.setattr(web, "manager", JobManager())
    with TestClient(web.app) as test_client:
        yield test_client


def create(client: TestClient, url: str) -> dict[str, Any]:
    response = client.post("/api/jobs", json={"url": url})
    assert response.status_code == 201, response.text
    data: dict[str, Any] = response.json()
    ids = ",".join(j["id"] for j in data["jobs"])
    wait_for(lambda: all(j["status"] == "done" for j in client.get(f"/api/jobs?ids={ids}").json()))
    return data


def test_single_link_end_to_end(client: TestClient) -> None:
    created = create(client, "https://www.youtube.com/watch?v=1")
    assert created["playlist"] is None
    [job] = client.get(f"/api/jobs?ids={created['jobs'][0]['id']}").json()
    assert job["filename"] == "One.mp3"
    assert job["size"] == len(b"https://www.youtube.com/watch?v=1")
    assert job["expires_at"] is not None
    assert job["error"] is None

    response = client.get(f"/api/jobs/{job['id']}/file")
    assert response.status_code == 200
    assert response.headers["content-type"] == "audio/mpeg"
    assert 'filename="One.mp3"' in response.headers["content-disposition"]


def test_playlist_becomes_one_job_per_track_and_zips(client: TestClient) -> None:
    created = create(client, "https://soundcloud.com/a/sets/b")
    assert created["playlist"] == "My set"
    ids = ",".join(j["id"] for j in created["jobs"])

    response = client.get(f"/api/archive?ids={ids}&name=My set")
    assert response.status_code == 200
    assert "My%20set.zip" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert sorted(archive.namelist()) == ["three.mp3", "two (2).mp3", "two.mp3"]
        assert archive.getinfo("two.mp3").compress_type == zipfile.ZIP_STORED
    assert not list(settings.workdir.glob("archive-*.zip"))  # deleted once sent


def test_archive_name_falls_back_to_the_app_name(client: TestClient) -> None:
    created = create(client, "https://www.youtube.com/watch?v=1")
    response = client.get(f"/api/archive?ids={created['jobs'][0]['id']}&name=")
    assert 'filename="Platine.zip"' in response.headers["content-disposition"]


@pytest.mark.parametrize(
    ("url", "status", "code"),
    [
        ("https://example.com/", 400, "unsupported_site"),
        ("https://example.com/empty", 400, "no_tracks"),
        ("https://example.com/bug", 400, "unexpected"),
    ],
)
def test_errors_carry_a_code_and_an_english_message(client: TestClient, url: str, status: int, code: str) -> None:
    response = client.post("/api/jobs", json={"url": url})
    assert response.status_code == status
    detail = response.json()["detail"]
    assert detail["code"] == code
    assert detail["message"]


def test_unexpected_resolve_failures_are_logged(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    client.post("/api/jobs", json={"url": "https://example.com/bug"})
    assert "Unexpected failure while reading https://example.com/bug" in caplog.text


def test_queue_limit(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "max_queued", 1)
    response = client.post("/api/jobs", json={"url": "https://soundcloud.com/a/sets/b"})
    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "queue_full"


def test_unknown_jobs_are_left_out_and_missing_files_are_404(client: TestClient) -> None:
    assert client.get("/api/jobs?ids=nope,").json() == []
    assert client.get("/api/jobs/nope/file").json()["detail"]["code"] == "file_gone"
    assert client.get("/api/archive?ids=nope").json()["detail"]["code"] == "archive_empty"
    assert client.post("/api/jobs/nope/cancel").json()["detail"]["code"] == "job_not_found"


def test_failed_job_exposes_its_error(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def fails(track: Track, dest: Path, **kwargs: Any) -> Path:
        raise UserError("ytm_no_match", "Track not found on YouTube Music.")

    monkeypatch.setattr(jobs, "download_mp3", fails)
    job_id = client.post("/api/jobs", json={"url": "https://www.youtube.com/watch?v=1"}).json()["jobs"][0]["id"]
    wait_for(lambda: client.get(f"/api/jobs?ids={job_id}").json()[0]["status"] == "error")
    [job] = client.get(f"/api/jobs?ids={job_id}").json()
    assert job["error"] == {"code": "ytm_no_match", "message": "Track not found on YouTube Music."}


def test_cancel_and_delete(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()

    def slow(track: Track, dest: Path, *, cancel: threading.Event, **kwargs: Any) -> Path:
        cancel.wait(5)
        release.set()
        raise UserError("cancelled", "cancelled")

    monkeypatch.setattr(jobs, "download_mp3", slow)
    job_id = client.post("/api/jobs", json={"url": "https://www.youtube.com/watch?v=1"}).json()["jobs"][0]["id"]
    assert client.post(f"/api/jobs/{job_id}/cancel").status_code == 200
    release.wait(5)
    wait_for(lambda: client.get(f"/api/jobs?ids={job_id}").json()[0]["status"] == "cancelled")
    assert client.delete(f"/api/jobs/{job_id}").status_code == 204
    assert client.get(f"/api/jobs?ids={job_id}").json() == []


def test_finished_jobs_are_purged_in_the_background(monkeypatch: pytest.MonkeyPatch) -> None:
    purged = threading.Event()
    manager = JobManager()
    monkeypatch.setattr(manager, "purge", purged.set)
    monkeypatch.setattr(web, "manager", manager)
    monkeypatch.setattr(web, "PURGE_INTERVAL", 0.01)
    with TestClient(web.app):
        assert purged.wait(5)


def test_config_health_metrics_and_page(client: TestClient) -> None:
    assert client.get("/api/config").json() == {"file_ttl": 3600, "max_playlist_items": 100}
    assert client.get("/healthz").json() == {"status": "ok"}
    assert "platine_jobs_active" in client.get("/metrics").text
    page = client.get("/")
    assert page.status_code == 200 and "<title>Platine</title>" in page.text


def basic(credentials: bytes) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(credentials).decode()}


def test_basic_auth_protects_everything_but_probes(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "auth_password", "s3cret")
    denied = client.get("/")
    assert denied.status_code == 401
    assert denied.headers["www-authenticate"] == 'Basic realm="Platine", charset="UTF-8"'
    assert client.get("/", headers=basic(b"platine:wrong")).status_code == 401
    assert client.get("/", headers=basic(b"someone:s3cret")).status_code == 401
    assert client.get("/", headers=basic(b"\xff\xfe")).status_code == 401  # not UTF-8
    assert client.get("/", headers={"Authorization": "Basic !!!"}).status_code == 401  # not base64
    assert client.get("/", headers={"Authorization": "Bearer token"}).status_code == 401
    assert client.get("/", headers=basic(b"platine:s3cret")).status_code == 200
    assert client.get("/healthz").status_code == 200
    assert client.get("/metrics").status_code == 200


def test_service_worker_precaches_the_app_with_content_revisions(client: TestClient) -> None:
    response = client.get("/sw.js")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["cache-control"] == "no-cache"
    first_line = response.text.splitlines()[0]
    manifest = json.loads(first_line.removeprefix("const PRECACHE = ").removesuffix(";"))
    urls = {entry["url"] for entry in manifest}
    assert {"/", "/app.css", "/manifest.webmanifest", "/brand/icon-192.png"} <= urls
    assert any(url.startswith("/js/") for url in urls)
    assert "/sw.js" not in urls
    assert not any(url.endswith((".md", ".map", ".woff", "LICENSE")) or "/screenshot-" in url for url in urls)
    assert all(len(entry["revision"]) == 16 for entry in manifest)
    assert "workbox.setConfig" in response.text


def test_manifest_is_served_as_a_web_app_manifest(client: TestClient) -> None:
    response = client.get("/manifest.webmanifest")
    assert response.headers["content-type"].startswith("application/manifest+json")
    manifest = response.json()
    assert manifest["name"] == "Platine"
    assert manifest["share_target"]["params"]["text"] == "text"
    for icon in manifest["icons"] + manifest["screenshots"]:
        assert client.get(f"/{icon['src']}").status_code == 200, icon["src"]
