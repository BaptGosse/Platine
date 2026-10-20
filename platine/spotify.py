"""Spotify protects its audio with DRM: read the track details on Spotify, then download
the same track from YouTube Music and write the Spotify tags into it."""

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import requests
from mutagen.id3 import APIC, ID3, TALB, TDRC, TIT2, TPE1, TRCK, ID3NoHeaderError
from requests.adapters import HTTPAdapter
from spotify_scraper import NotFoundError, SpotifyClient, SpotifyScraperError
from urllib3.util import Retry
from ytmusicapi import YTMusic

from .config import settings
from .errors import UserError
from .models import Resolved, Track

SPOTIFY_LINK = re.compile(
    r"(?:https?://open\.spotify\.com/(?:intl-[\w-]+/)?|spotify:)(?P<kind>[a-z]+)[/:](?P<id>[A-Za-z0-9]+)"
)
MIN_MATCH_SCORE = 45
SPOTIFY_UNAVAILABLE = "Spotify did not respond properly. Try again in a moment."


@dataclass
class SpotifyTrack:
    """Spotify details used to find the track elsewhere and to tag the MP3."""

    id: str
    title: str
    artists: list[str]
    album: str | None
    year: int | None
    track_number: int | None
    duration: float
    cover_url: str | None

    @property
    def artist(self) -> str:
        """Every artist, joined for display and tags."""
        return ", ".join(self.artists)


def is_spotify(url: str) -> bool:
    """Whether `url` is a Spotify link or URI."""
    return SPOTIFY_LINK.match(url.strip()) is not None


def _client() -> SpotifyClient:
    # spotifyscraper already retries network errors on its own (4 attempts, growing delay).
    return SpotifyClient(proxy=settings.proxy)


def _proxies() -> dict[str, str] | None:
    return {"http": settings.proxy, "https": settings.proxy} if settings.proxy else None


def _http_session() -> requests.Session:
    """HTTP session that retries transient errors (429, 5xx), including YouTube Music POST requests."""
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=(429, 500, 502, 503, 504), allowed_methods=None)
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.proxies.update(_proxies() or {})
    return session


def _largest_image(images: Iterable[Any] | None) -> str | None:
    images = [i for i in images or () if i.url]
    return max(images, key=lambda i: i.width or 0).url if images else None


def _track(t: Any, *, album: str | None = None, cover: str | None = None) -> Track:
    return Track(
        url=f"https://open.spotify.com/track/{t.id}",
        source="Spotify",
        title=t.name,
        artist=", ".join(a.name for a in t.artists),
        album=album or (t.album.name if t.album else None),
        duration=t.duration_ms / 1000 if t.duration_ms else None,
        thumbnail=cover or _largest_image(t.images or (t.album.images if t.album else ())),
        spotify_id=t.id,
    )


def resolve(url: str) -> Resolved:
    """Tracks of a Spotify track, album or playlist link."""
    match = SPOTIFY_LINK.match(url.strip())
    kind = match["kind"] if match else None
    try:
        with _client() as client:
            if kind == "track":
                return Resolved([_track(client.get_track(url))])
            if kind == "album":
                album = client.get_album(url)
                cover = _largest_image(album.images)
                tracks = [_track(t, album=album.name, cover=cover) for t in album.tracks if t.id]
                return Resolved(tracks[: settings.max_playlist_items], playlist=album.name)
            if kind == "playlist":
                playlist = client.get_playlist(url, max_tracks=settings.max_playlist_items)
                tracks = [_track(item.track) for item in playlist.tracks if item.track and item.track.id]
                return Resolved(tracks, playlist=playlist.name)
    except NotFoundError as exc:
        raise UserError(
            "spotify_not_found", "This Spotify content was not found: is the link private or deleted?"
        ) from exc
    except SpotifyScraperError as exc:
        raise UserError("spotify_unavailable", SPOTIFY_UNAVAILABLE) from exc
    raise UserError("spotify_unsupported", "Only Spotify tracks, albums and playlists are supported.")


def track_meta(spotify_id: str) -> SpotifyTrack:
    """Full Spotify details of a track: album, year, number and cover."""
    try:
        with _client() as client:
            t = client.get_track(spotify_id)
    except SpotifyScraperError as exc:
        raise UserError("spotify_unavailable", SPOTIFY_UNAVAILABLE) from exc
    return SpotifyTrack(
        id=t.id,
        title=t.name,
        artists=[a.name for a in t.artists],
        album=t.album.name if t.album else None,
        year=t.release_date.year if t.release_date else None,
        track_number=t.track_number,
        duration=t.duration_ms / 1000,
        cover_url=_largest_image(t.images or (t.album.images if t.album else ())),
    )


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _score(result: dict[str, Any], meta: SpotifyTrack) -> float:
    """Scores a YouTube Music result: title, artist, duration and album must match."""
    score = 40 * SequenceMatcher(None, _normalize(result.get("title") or ""), _normalize(meta.title)).ratio()
    wanted = {_normalize(a) for a in meta.artists}
    if wanted & {_normalize(a["name"]) for a in result.get("artists") or []}:
        score += 30
    if result.get("duration_seconds"):
        gap = abs(result["duration_seconds"] - meta.duration)
        score += 20 if gap <= 3 else 8 if gap <= 10 else -25 if gap > 30 else 0
    album = (result.get("album") or {}).get("name")
    if album and meta.album and _normalize(album) == _normalize(meta.album):
        score += 10
    return score


def find_on_youtube_music(meta: SpotifyTrack) -> str:
    """YouTube Music link of the recording that best matches `meta`."""
    ytmusic = YTMusic(requests_session=_http_session())
    query = f"{meta.artists[0] if meta.artists else ''} {meta.title}"
    try:
        # "songs" are the official audio releases; fall back to videos when none fits.
        for search_filter in ("songs", "videos"):
            results = [r for r in ytmusic.search(query, filter=search_filter, limit=10) if r.get("videoId")]
            best = max(results, key=lambda r: _score(r, meta), default=None)
            if best and _score(best, meta) >= MIN_MATCH_SCORE:
                return f"https://music.youtube.com/watch?v={best['videoId']}"
    except requests.RequestException as exc:
        raise UserError("ytm_unavailable", "YouTube Music did not respond. Try again in a moment.") from exc
    raise UserError("ytm_no_match", "Track not found on YouTube Music.")


def write_tags(mp3: Path, meta: SpotifyTrack) -> None:
    """Replaces the tags that came from YouTube with the Spotify ones, square cover included."""
    try:
        tags = ID3(mp3)
    except ID3NoHeaderError:
        tags = ID3()
    tags.setall("TIT2", [TIT2(encoding=3, text=meta.title)])
    tags.setall("TPE1", [TPE1(encoding=3, text=meta.artist)])
    if meta.album:
        tags.setall("TALB", [TALB(encoding=3, text=meta.album)])
    if meta.year:
        tags.setall("TDRC", [TDRC(encoding=3, text=str(meta.year))])
    if meta.track_number:
        tags.setall("TRCK", [TRCK(encoding=3, text=str(meta.track_number))])
    if meta.cover_url:
        try:
            cover = _http_session().get(meta.cover_url, timeout=15)
            cover.raise_for_status()
        except requests.RequestException:
            pass  # keep the YouTube cover that is already embedded
        else:
            tags.setall("APIC", [APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover.content)])
    tags.save(mp3)
