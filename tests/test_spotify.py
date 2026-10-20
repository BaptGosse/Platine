from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest
import requests
import responses
from mutagen.id3 import ID3
from spotify_scraper import NotFoundError, SpotifyScraperError

from platine import spotify
from platine.config import settings
from platine.errors import UserError

COVER = "https://i.scdn.co/image/discovery640"


def sp_track(track_id: str = "t1", name: str = "One More Time", **extra: Any) -> SimpleNamespace:
    fields: dict[str, Any] = {
        "id": track_id,
        "name": name,
        "artists": (SimpleNamespace(name="Daft Punk"),),
        "duration_ms": 320_357,
        "images": (),
        "album": None,
        "release_date": None,
        "track_number": None,
    }
    return SimpleNamespace(**(fields | extra))


def sp_album() -> SimpleNamespace:
    images = (SimpleNamespace(url="small", width=64), SimpleNamespace(url=COVER, width=640))
    return SimpleNamespace(name="Discovery", images=images)


class FakeClient:
    track = sp_track(album=sp_album(), release_date=datetime(2001, 3, 12, tzinfo=UTC), track_number=1)
    album = SimpleNamespace(
        name="Discovery",
        images=sp_album().images,
        tracks=[sp_track("a"), sp_track("b", "Aerodynamic", duration_ms=None), sp_track("")],
    )
    playlist = SimpleNamespace(name="Top", tracks=[SimpleNamespace(track=sp_track("p1")), SimpleNamespace(track=None)])
    error: Exception | None = None
    kwargs: ClassVar[dict[str, Any]] = {}

    def __init__(self, **kwargs: Any) -> None:
        FakeClient.kwargs = kwargs

    def __enter__(self) -> "FakeClient":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def _answer(self, value: Any) -> Any:
        if FakeClient.error:
            raise FakeClient.error
        return value

    def get_track(self, value: str) -> SimpleNamespace:
        return self._answer(self.track)

    def get_album(self, value: str) -> SimpleNamespace:
        return self._answer(self.album)

    def get_playlist(self, value: str, max_tracks: int | None = None) -> SimpleNamespace:
        return self._answer(self.playlist)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> type[FakeClient]:
    FakeClient.error = None
    monkeypatch.setattr(spotify, "SpotifyClient", FakeClient)
    return FakeClient


@pytest.mark.parametrize(
    ("url", "is_spotify"),
    [
        ("https://open.spotify.com/track/0DiWol3AO6WpXZgp0goxAV", True),
        ("https://open.spotify.com/intl-fr/album/2noRn2Aes5aoNVsU6iWThc?si=abc", True),
        ("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M", True),
        ("https://www.youtube.com/watch?v=x", False),
    ],
)
def test_is_spotify(url: str, is_spotify: bool) -> None:
    assert spotify.is_spotify(url) is is_spotify


def test_resolve_track(client: type[FakeClient], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "proxy", "http://proxy:3128")
    [track] = spotify.resolve("https://open.spotify.com/track/t1").tracks
    assert (track.title, track.artist, track.album, track.thumbnail) == (
        "One More Time",
        "Daft Punk",
        "Discovery",
        COVER,
    )
    assert track.spotify_id == "t1"
    assert track.url == "https://open.spotify.com/track/t1"
    assert track.duration == pytest.approx(320.357)
    assert client.kwargs == {"proxy": "http://proxy:3128"}


def test_resolve_album_uses_the_album_cover_and_skips_tracks_without_id(client: type[FakeClient]) -> None:
    resolved = spotify.resolve("https://open.spotify.com/album/x")
    assert resolved.playlist == "Discovery"
    assert [t.title for t in resolved.tracks] == ["One More Time", "Aerodynamic"]
    assert {t.thumbnail for t in resolved.tracks} == {COVER}
    assert resolved.tracks[1].duration is None


def test_resolve_playlist_skips_empty_items(client: type[FakeClient]) -> None:
    resolved = spotify.resolve("https://open.spotify.com/playlist/x")
    assert resolved.playlist == "Top"
    assert [t.spotify_id for t in resolved.tracks] == ["p1"]
    assert resolved.tracks[0].album is None and resolved.tracks[0].thumbnail is None


@pytest.mark.parametrize("url", ["https://open.spotify.com/artist/x", "not spotify at all"])
def test_resolve_rejects_artists_podcasts_and_other_links(client: type[FakeClient], url: str) -> None:
    with pytest.raises(UserError) as caught:
        spotify.resolve(url)
    assert caught.value.code == "spotify_unsupported"


@pytest.mark.parametrize(
    ("error", "code"),
    [(NotFoundError("404"), "spotify_not_found"), (SpotifyScraperError("boom"), "spotify_unavailable")],
)
def test_resolve_translates_spotify_errors(client: type[FakeClient], error: Exception, code: str) -> None:
    client.error = error
    with pytest.raises(UserError) as caught:
        spotify.resolve("https://open.spotify.com/track/x")
    assert caught.value.code == code


def test_track_meta(client: type[FakeClient]) -> None:
    meta = spotify.track_meta("t1")
    assert (meta.album, meta.year, meta.track_number, meta.cover_url) == ("Discovery", 2001, 1, COVER)


def test_track_meta_without_album_or_date(client: type[FakeClient], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(FakeClient, "track", sp_track())
    meta = spotify.track_meta("t1")
    assert (meta.album, meta.year, meta.cover_url) == (None, None, None)


def test_track_meta_translates_spotify_errors(client: type[FakeClient]) -> None:
    client.error = SpotifyScraperError("boom")
    with pytest.raises(UserError) as caught:
        spotify.track_meta("t1")
    assert caught.value.code == "spotify_unavailable"


def meta(**overrides: Any) -> spotify.SpotifyTrack:
    fields: dict[str, Any] = {
        "id": "t1", "title": "One More Time", "artists": ["Daft Punk"], "album": "Discovery",
        "year": 2001, "track_number": 1, "duration": 320.4, "cover_url": COVER,
    }  # fmt: skip
    return spotify.SpotifyTrack(**(fields | overrides))


def ytm(video_id: str, title: str, artist: str, seconds: int | None, album: str | None = None) -> dict[str, Any]:
    return {
        "videoId": video_id,
        "title": title,
        "artists": [{"name": artist}],
        "duration_seconds": seconds,
        "album": {"name": album} if album else None,
    }


class FakeYTMusic:
    results: ClassVar[dict[str, list[dict[str, Any]]]] = {}
    queries: ClassVar[list[tuple[str, str]]] = []
    session: ClassVar[requests.Session | None] = None

    def __init__(self, requests_session: requests.Session) -> None:
        FakeYTMusic.session = requests_session

    def search(self, query: str, filter: str, limit: int) -> list[dict[str, Any]]:  # pylint: disable=redefined-builtin  # ytmusicapi name
        FakeYTMusic.queries.append((query, filter))
        return FakeYTMusic.results.get(filter, [])


@pytest.fixture
def ytmusic(monkeypatch: pytest.MonkeyPatch) -> type[FakeYTMusic]:
    FakeYTMusic.results, FakeYTMusic.queries = {}, []
    monkeypatch.setattr(spotify, "YTMusic", FakeYTMusic)
    return FakeYTMusic


def test_match_prefers_the_album_version_over_edits_and_covers(ytmusic: type[FakeYTMusic]) -> None:
    ytmusic.results["songs"] = [
        ytm("edit", "One More Time (Radio Edit)", "Daft Punk", 321, "One More Time"),
        ytm("album", "One More Time", "Daft Punk", 320, "Discovery"),
        ytm("cover", "One More Time", "Robin Schulz", 200),
        ytm("live", "One More Time (Live)", "Daft Punk", 335),
        ytm("unknown-length", "One More Time", "Someone", None),
        {"title": "no videoId"},
    ]
    assert spotify.find_on_youtube_music(meta()) == "https://music.youtube.com/watch?v=album"
    assert ytmusic.queries == [("Daft Punk One More Time", "songs")]


def test_match_falls_back_to_videos(ytmusic: type[FakeYTMusic]) -> None:
    ytmusic.results["songs"] = [ytm("other", "Something Else", "Someone", 100)]
    ytmusic.results["videos"] = [ytm("clip", "Daft Punk - One More Time (Official Video)", "Daft Punk", 322)]
    assert spotify.find_on_youtube_music(meta()) == "https://music.youtube.com/watch?v=clip"
    assert [kind for _, kind in ytmusic.queries] == ["songs", "videos"]


def test_match_gives_up_when_nothing_fits(ytmusic: type[FakeYTMusic]) -> None:
    ytmusic.results["songs"] = [ytm("other", "Something Else", "Someone", 100)]
    with pytest.raises(UserError) as caught:
        spotify.find_on_youtube_music(meta(artists=[]))
    assert caught.value.code == "ytm_no_match"
    assert ytmusic.queries[0] == (" One More Time", "songs")


def test_match_translates_network_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class Down(FakeYTMusic):
        def search(self, query: str, filter: str, limit: int) -> list[dict[str, Any]]:  # pylint: disable=redefined-builtin  # ytmusicapi name
            raise requests.ConnectionError("down")

    monkeypatch.setattr(spotify, "YTMusic", Down)
    with pytest.raises(UserError) as caught:
        spotify.find_on_youtube_music(meta())
    assert caught.value.code == "ytm_unavailable"


def test_http_session_retries_and_uses_the_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "proxy", "http://proxy:3128")
    session = spotify._http_session()
    assert session.proxies == {"http": "http://proxy:3128", "https": "http://proxy:3128"}
    retries = session.get_adapter("https://music.youtube.com").max_retries  # type: ignore[attr-defined]
    assert retries.total == 3 and 429 in retries.status_forcelist


@responses.activate
def test_write_tags_replaces_youtube_tags_with_spotify_ones(tmp_path: Path) -> None:
    responses.get(COVER, body=b"\xff\xd8jpeg", content_type="image/jpeg")
    mp3 = tmp_path / "a.mp3"
    mp3.write_bytes(b"\xff\xfb\x90\x00" * 64)
    spotify.write_tags(mp3, meta(artists=["Olivia Rodrigo", "Chappell Roan"]))
    tags = ID3(mp3)
    assert str(tags["TIT2"]) == "One More Time"
    assert str(tags["TPE1"]) == "Olivia Rodrigo, Chappell Roan"
    assert (str(tags["TALB"]), str(tags["TDRC"]), str(tags["TRCK"])) == ("Discovery", "2001", "1")
    assert tags.getall("APIC")[0].data == b"\xff\xd8jpeg"


@responses.activate
def test_write_tags_keeps_going_when_the_cover_cannot_be_downloaded(tmp_path: Path) -> None:
    responses.get(COVER, status=404)
    mp3 = tmp_path / "a.mp3"
    mp3.write_bytes(b"\xff\xfb\x90\x00" * 64)
    spotify.write_tags(mp3, meta(album=None, year=None, track_number=None))
    tags = ID3(mp3)
    assert str(tags["TIT2"]) == "One More Time"
    assert not tags.getall("APIC") and "TALB" not in tags


def test_write_tags_without_cover_keeps_the_existing_one(tmp_path: Path) -> None:
    mp3 = tmp_path / "a.mp3"
    mp3.write_bytes(b"\xff\xfb\x90\x00" * 64)
    spotify.write_tags(mp3, meta(cover_url=None))
    assert not ID3(mp3).getall("APIC")
