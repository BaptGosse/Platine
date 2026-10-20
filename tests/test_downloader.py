import threading
from pathlib import Path
from typing import Any

import pytest

from platine import downloader
from platine.config import settings
from platine.downloader import Cancelled, _filename, download_mp3
from platine.errors import UserError
from platine.models import Track
from platine.spotify import SpotifyTrack
from tests.conftest import FakeYoutubeDL, video_info


@pytest.mark.parametrize(
    ("title", "artist", "expected"),
    [
        ("Never Gonna Give You Up", "Rick Astley", "Rick Astley - Never Gonna Give You Up.mp3"),
        ("Rick Astley - Never Gonna Give You Up", "Rick Astley", "Rick Astley - Never Gonna Give You Up.mp3"),
        ("Title", None, "Title.mp3"),
        (None, None, "audio.mp3"),
        ("AC/DC: Back in Black?", None, "AC⧸DC： Back in Black？.mp3"),
    ],
)
def test_filename(title: str | None, artist: str | None, expected: str) -> None:
    assert _filename(title, artist) == expected


def youtube_track(**overrides: Any) -> Track:
    return Track(url="https://www.youtube.com/watch?v=dQw4w9WgXcQ", source="YouTube", **overrides)


def test_download_reuses_resolved_info_and_reports_each_stage(fake_ydl: type[FakeYoutubeDL], tmp_path: Path) -> None:
    stages: list[tuple[str, float | None]] = []
    metas: list[dict[str, Any]] = []
    track = youtube_track(info=video_info())

    mp3 = download_mp3(
        track, tmp_path / "job",
        on_progress=lambda stage, fraction=None, *_: stages.append((stage, fraction)),
        on_meta=metas.append,
    )  # fmt: skip

    assert mp3 == tmp_path / "job" / "Rick Astley - Never Gonna Give You Up (Official Video).mp3"
    assert mp3.exists()
    assert fake_ydl.instances[0].extracted == []  # no second extraction
    assert stages == [("downloading", 0.4), ("downloading", None), ("converting", None)]
    assert metas[0]["artist"] == "Rick Astley"


def test_download_without_callbacks_extracts_then_downloads(fake_ydl: type[FakeYoutubeDL], tmp_path: Path) -> None:
    fake_ydl.results = [video_info()]
    mp3 = download_mp3(youtube_track(), tmp_path)
    assert fake_ydl.instances[0].extracted == ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]
    assert mp3.exists()


def test_download_unwraps_a_playlist_result(fake_ydl: type[FakeYoutubeDL], tmp_path: Path) -> None:
    fake_ydl.wrap_in_playlist = True
    mp3 = download_mp3(youtube_track(info=video_info()), tmp_path)
    assert mp3.name == "Rick Astley - Never Gonna Give You Up (Official Video).mp3"


def test_download_asks_ffmpeg_for_320_kbps_mp3_with_tags_and_cover(
    fake_ydl: type[FakeYoutubeDL], tmp_path: Path
) -> None:
    fake_ydl.results = [video_info()]
    download_mp3(youtube_track(), tmp_path)
    opts = fake_ydl.instances[0].opts
    extract = next(pp for pp in opts["postprocessors"] if pp["key"] == "FFmpegExtractAudio")
    assert (extract["preferredcodec"], extract["preferredquality"]) == ("mp3", "320")
    assert {pp["key"] for pp in opts["postprocessors"]} >= {"FFmpegMetadata", "EmbedThumbnail"}
    assert opts["format"] == "bestaudio/best"
    assert opts["writethumbnail"] is True


def test_download_rejects_live_streams(fake_ydl: type[FakeYoutubeDL], tmp_path: Path) -> None:
    fake_ydl.results = [video_info(is_live=True)]
    with pytest.raises(UserError) as caught:
        download_mp3(youtube_track(), tmp_path)
    assert caught.value.code == "live_not_supported"


def test_download_stops_when_cancelled(fake_ydl: type[FakeYoutubeDL], tmp_path: Path) -> None:
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(Cancelled):
        download_mp3(youtube_track(info=video_info()), tmp_path, cancel=cancel)


def test_download_keeps_going_while_not_cancelled(fake_ydl: type[FakeYoutubeDL], tmp_path: Path) -> None:
    assert download_mp3(youtube_track(info=video_info()), tmp_path, cancel=threading.Event()).exists()


def test_download_uses_a_copy_of_the_cookies_file(
    fake_ydl: type[FakeYoutubeDL], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    monkeypatch.setattr(settings, "cookies_file", cookies)
    monkeypatch.setattr(settings, "proxy", "http://proxy:3128")
    download_mp3(youtube_track(info=video_info()), tmp_path / "job")
    opts = fake_ydl.instances[0].opts
    assert opts["cookiefile"] == str(tmp_path / "job" / "cookies.txt")
    assert opts["proxy"] == "http://proxy:3128"


def test_spotify_track_is_matched_on_youtube_music_and_tagged_from_spotify(
    fake_ydl: type[FakeYoutubeDL], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = SpotifyTrack(
        id="t1", title="One More Time", artists=["Daft Punk"], album="Discovery",
        year=2001, track_number=1, duration=320.4, cover_url=None,
    )  # fmt: skip
    tagged: list[Path] = []
    monkeypatch.setattr(downloader.spotify, "track_meta", lambda spotify_id: meta)
    monkeypatch.setattr(downloader.spotify, "find_on_youtube_music", lambda m: "https://music.youtube.com/watch?v=yt")
    monkeypatch.setattr(downloader.spotify, "write_tags", lambda mp3, m: tagged.append(mp3))
    fake_ydl.results = [video_info(id="yt", title="One More Time (Remastered)", uploader="Daft Punk - Topic")]
    metas: list[dict[str, Any]] = []
    stages: list[str] = []

    track = Track(url="https://open.spotify.com/track/t1", source="Spotify", spotify_id="t1")
    mp3 = download_mp3(track, tmp_path, on_meta=metas.append, on_progress=lambda stage, *_: stages.append(stage))

    assert fake_ydl.instances[0].extracted == ["https://music.youtube.com/watch?v=yt"]
    assert mp3.name == "Daft Punk - One More Time.mp3"  # named after Spotify, not YouTube
    assert tagged == [tmp_path / "yt.mp3"]
    assert not metas  # Spotify details win
    assert stages[0] == "matching"
