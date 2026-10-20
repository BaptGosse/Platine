import pytest

from platine import sources
from platine.config import settings
from platine.errors import UserError
from platine.models import Resolved, Track
from tests.conftest import FakeYoutubeDL, video_info


@pytest.mark.parametrize(
    ("url", "name"),
    [
        ("https://www.youtube.com/watch?v=x", "YouTube"),
        ("https://m.youtube.com/watch?v=x", "YouTube"),
        ("https://youtu.be/x", "YouTube"),
        ("https://music.youtube.com/watch?v=x", "YouTube Music"),
        ("https://soundcloud.com/forss/flickermood", "SoundCloud"),
        ("https://daftpunk.bandcamp.com/album/x", "Bandcamp"),
        ("https://www.radiofrance.fr/emission", "radiofrance.fr"),
        ("file:///etc/passwd", "Link"),
    ],
)
def test_site_name(url: str, name: str) -> None:
    assert sources.site_name(url) == name


def test_describe_prefers_music_metadata_and_strips_topic_channels() -> None:
    info = {"title": "One More Time (Official Audio)", "track": "One More Time", "uploader": "Daft Punk - Topic"}
    assert sources.describe(info)["title"] == "One More Time"
    assert sources.describe(info)["artist"] == "Daft Punk"
    assert sources.describe({"artists": ["A", "B"], "title": "t"})["artist"] == "A, B"
    assert sources.describe({"title": "t"})["artist"] is None


def test_describe_takes_the_last_listed_thumbnail() -> None:
    info = {"thumbnails": [{"url": "small.jpg"}, {"url": "big.jpg"}, {"id": "no-url"}]}
    assert sources.describe(info)["thumbnail"] == "big.jpg"
    assert sources.describe({})["thumbnail"] is None


def test_resolve_single_video_keeps_the_extraction(fake_ydl: type[FakeYoutubeDL]) -> None:
    fake_ydl.results = [video_info()]
    resolved = sources.resolve("  https://www.youtube.com/watch?v=dQw4w9WgXcQ  ")
    [track] = resolved.tracks
    assert resolved.playlist is None
    assert track.source == "YouTube"
    assert track.artist == "Rick Astley"
    assert track.info is not None and track.info["id"] == "dQw4w9WgXcQ"
    assert fake_ydl.instances[0].opts["noplaylist"] is True


def test_resolve_follows_redirections(fake_ydl: type[FakeYoutubeDL]) -> None:
    fake_ydl.results = [{"_type": "url", "url": "https://youtu.be/dQw4w9WgXcQ"}, video_info()]
    resolved = sources.resolve("https://blog.example/article-with-a-video")
    assert fake_ydl.instances[0].extracted[1] == "https://youtu.be/dQw4w9WgXcQ"
    assert resolved.tracks[0].title == video_info()["title"]


def test_resolve_stops_following_endless_redirections(fake_ydl: type[FakeYoutubeDL]) -> None:
    fake_ydl.results = [{"_type": "url_transparent", "url": f"https://example.com/{n}"} for n in range(4)]
    [track] = sources.resolve("https://example.com/start").tracks
    assert len(fake_ydl.instances[0].extracted) == 4
    assert track.url == "https://example.com/start"


def test_resolve_playlist_splits_into_tracks_and_respects_the_limit(
    fake_ydl: type[FakeYoutubeDL], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "max_playlist_items", 2)
    entries = [
        {"_type": "url", "url": f"https://www.youtube.com/watch?v={i}", "title": f"Track {i}", "duration": 60}
        for i in range(5)
    ]
    fake_ydl.results = [
        {"_type": "playlist", "title": "My playlist", "entries": iter([None, {"title": "no url"}, *entries])}
    ]
    resolved = sources.resolve("https://music.youtube.com/playlist?list=PL1")
    assert resolved.playlist == "My playlist"
    assert [t.title for t in resolved.tracks] == ["Track 0"]
    assert all(t.source == "YouTube Music" and t.info is None for t in resolved.tracks)


def test_untitled_playlist_gets_a_default_name(fake_ydl: type[FakeYoutubeDL]) -> None:
    fake_ydl.results = [{"_type": "multi_video", "entries": [{"webpage_url": "https://vimeo.com/1"}]}]
    resolved = sources.resolve("https://vimeo.com/showcase/1")
    assert resolved.playlist == "Playlist"
    assert resolved.tracks[0].url == "https://vimeo.com/1"


def test_resolve_rejects_live_streams(fake_ydl: type[FakeYoutubeDL]) -> None:
    fake_ydl.results = [video_info(is_live=True)]
    with pytest.raises(UserError, match="Live streams") as caught:
        sources.resolve("https://www.youtube.com/watch?v=live")
    assert caught.value.code == "live_not_supported"


def test_resolve_rejects_text_that_is_not_a_link() -> None:
    with pytest.raises(UserError) as caught:
        sources.resolve("never gonna give you up")
    assert caught.value.code == "not_a_link"


def test_resolve_hands_spotify_links_to_the_spotify_module(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = Resolved([Track(url="https://open.spotify.com/track/x", source="Spotify")])
    monkeypatch.setattr(sources.spotify, "resolve", lambda url: expected)
    assert sources.resolve("https://open.spotify.com/track/x") is expected
    assert sources.resolve("spotify:track:x") is expected
