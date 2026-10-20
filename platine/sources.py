"""Turns a link (track, video, playlist, album) into a list of tracks to download."""

import itertools
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from yt_dlp import YoutubeDL

from . import spotify, ytdlp
from .config import settings
from .errors import LIVE_NOT_SUPPORTED, UserError
from .models import Resolved, Track

SITE_NAMES = {
    "music.youtube.com": "YouTube Music",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
    "soundcloud.com": "SoundCloud",
    "open.spotify.com": "Spotify",
    "bandcamp.com": "Bandcamp",
    "mixcloud.com": "Mixcloud",
    "vimeo.com": "Vimeo",
    "dailymotion.com": "Dailymotion",
    "twitch.tv": "Twitch",
    "tiktok.com": "TikTok",
    "instagram.com": "Instagram",
    "facebook.com": "Facebook",
    "x.com": "X",
    "twitter.com": "X",
    "reddit.com": "Reddit",
    "archive.org": "Internet Archive",
}


def site_name(url: str) -> str:
    """Display name of the site a link belongs to."""
    host = (urlparse(url).hostname or "").removeprefix("www.").removeprefix("m.")
    if host in SITE_NAMES:
        return SITE_NAMES[host]
    for domain, name in SITE_NAMES.items():
        if host.endswith("." + domain):
            return name
    return host or "Link"


def _thumbnail(info: dict) -> str | None:
    if info.get("thumbnail"):
        return info["thumbnail"]
    thumbnails = [t for t in info.get("thumbnails") or [] if t.get("url")]
    return thumbnails[-1]["url"] if thumbnails else None


def describe(info: dict) -> dict:
    """Title, artist, album... as they should be displayed, from the yt-dlp details."""
    artist = ", ".join(info.get("artists") or []) or info.get("artist") or info.get("uploader") or info.get("channel")
    return {
        "title": info.get("track") or info.get("title"),
        "artist": artist.removesuffix(" - Topic") if artist else None,
        "album": info.get("album"),
        "duration": info.get("duration"),
        "thumbnail": _thumbnail(info),
    }


def resolve(url: str) -> Resolved:
    """Reads `url` and returns the tracks it points to: one, or a whole playlist or album."""
    url = url.strip()
    if not urlparse(url).scheme.startswith("http") and not spotify.is_spotify(url):
        raise UserError("not_a_link", "This is not a valid link: it must start with https://")
    if spotify.is_spotify(url):
        return spotify.resolve(url)

    with (
        tempfile.TemporaryDirectory(prefix="resolve-") as tmp,
        YoutubeDL(ytdlp.options(Path(tmp), noplaylist=True)) as ydl,
    ):
        info = ydl.extract_info(url, download=False, process=False)
        # A page that points to another link (embedded player, short link...): follow it.
        for _ in range(3):
            if info.get("_type") not in ("url", "url_transparent"):
                break
            info = ydl.extract_info(info["url"], download=False, process=False)

    source = site_name(url)
    if info.get("_type") in ("playlist", "multi_video"):
        entries = itertools.islice((e for e in info.get("entries") or [] if e), settings.max_playlist_items)
        tracks = [
            Track(url=e.get("webpage_url") or e["url"], source=source, **describe(e))
            for e in entries
            if e.get("webpage_url") or e.get("url")
        ]
        return Resolved(tracks, playlist=info.get("title") or "Playlist")
    if info.get("is_live"):
        raise UserError("live_not_supported", LIVE_NOT_SUPPORTED)
    return Resolved([Track(url=info.get("webpage_url") or url, source=source, info=info, **describe(info))])
