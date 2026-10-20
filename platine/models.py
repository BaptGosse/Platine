"""Data passed between link reading, downloads and the job queue."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Track:
    """What we know about a track before downloading it."""

    url: str
    """Page of the track: this is what gets submitted again when a conversion is retried."""
    source: str
    """Name of the site it comes from, as displayed."""
    title: str | None = None
    artist: str | None = None
    album: str | None = None
    duration: float | None = None
    thumbnail: str | None = None
    spotify_id: str | None = None
    """Spotify track: the audio will be looked up on YouTube Music."""
    info: dict[str, Any] | None = field(default=None, repr=False)
    """yt-dlp extraction already done, reused for the download so it is not done twice."""


@dataclass
class Resolved:
    """Result of reading a link."""

    tracks: list[Track]
    playlist: str | None = None
    """Name of the playlist or album, when the link pointed to one."""
