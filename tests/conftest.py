import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, ClassVar

import pytest

import platine.downloader
import platine.sources
from platine.config import settings


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every test works in its own folder, without proxy, cookies or password."""
    monkeypatch.setattr(settings, "workdir", tmp_path / "work")
    monkeypatch.setattr(settings, "cookies_file", None)
    monkeypatch.setattr(settings, "proxy", None)
    monkeypatch.setattr(settings, "auth_password", None)
    monkeypatch.setattr(settings, "max_concurrent", 2)
    yield


def wait_for(condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition never met")
        time.sleep(0.01)


class FakeYoutubeDL:
    """Mimics the part of yt_dlp.YoutubeDL that Platine uses, without network or ffmpeg.

    `results`: what successive `extract_info` calls return.
    `wrap_in_playlist`: `process_ie_result` returns the track inside a playlist, as yt-dlp
    does for some pages.
    """

    results: ClassVar[list[dict[str, Any]]] = []
    instances: ClassVar[list["FakeYoutubeDL"]] = []
    wrap_in_playlist: ClassVar[bool] = False

    def __init__(self, opts: dict[str, Any]) -> None:
        self.opts = opts
        self.extracted: list[str] = []
        FakeYoutubeDL.instances.append(self)

    def __enter__(self) -> "FakeYoutubeDL":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def extract_info(self, url: str, download: bool = False, process: bool = True) -> dict[str, Any]:
        self.extracted.append(url)
        return dict(FakeYoutubeDL.results.pop(0))

    def process_ie_result(self, info: dict[str, Any], download: bool = True) -> dict[str, Any]:
        for hook in self.opts.get("progress_hooks", []):
            hook({"status": "downloading", "downloaded_bytes": 40, "total_bytes": 100, "speed": 2e6, "eta": 1})
            hook({"status": "downloading", "downloaded_bytes": 50})  # size unknown
            hook({"status": "finished", "downloaded_bytes": 100, "total_bytes": 100})
        for hook in self.opts.get("postprocessor_hooks", []):
            hook({"status": "started", "postprocessor": "ExtractAudio"})
            hook({"status": "finished", "postprocessor": "ExtractAudio"})
        target = Path(self.opts["outtmpl"].replace("%(id)s", info["id"]).replace("%(ext)s", "mp3"))
        target.write_bytes(b"\xff\xfb\x90\x00" * 64)
        result = {**info, "requested_downloads": [{"filepath": str(target)}]}
        if FakeYoutubeDL.wrap_in_playlist:
            return {"_type": "playlist", "entries": [None, result]}
        return result


@pytest.fixture
def fake_ydl(monkeypatch: pytest.MonkeyPatch) -> type[FakeYoutubeDL]:
    FakeYoutubeDL.results = []
    FakeYoutubeDL.instances = []
    FakeYoutubeDL.wrap_in_playlist = False
    monkeypatch.setattr(platine.sources, "YoutubeDL", FakeYoutubeDL)
    monkeypatch.setattr(platine.downloader, "YoutubeDL", FakeYoutubeDL)
    return FakeYoutubeDL


def video_info(**overrides: Any) -> dict[str, Any]:
    info: dict[str, Any] = {
        "id": "dQw4w9WgXcQ",
        "title": "Rick Astley - Never Gonna Give You Up (Official Video)",
        "uploader": "Rick Astley",
        "duration": 213,
        "webpage_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
    }
    return info | overrides
