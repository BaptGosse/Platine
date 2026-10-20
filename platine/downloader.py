"""Downloads a track and converts it to a 320 kbps MP3 with yt-dlp and ffmpeg."""

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL
from yt_dlp.utils import sanitize_filename

from . import spotify, ytdlp
from .errors import LIVE_NOT_SUPPORTED, UserError
from .models import Track
from .sources import describe

BITRATE_KBPS = "320"


class Cancelled(Exception):
    """Raised from a yt-dlp hook to stop a conversion the user cancelled."""


def _noop(*_args: object, **_kwargs: object) -> None:
    """Default callback: ignore the event."""


def _filename(title: str | None, artist: str | None) -> str:
    title = title or "audio"
    # Many YouTube titles already read "Artist - Title": do not repeat the artist.
    name = title if not artist or title.lower().startswith(artist.lower()) else f"{artist} - {title}"
    return sanitize_filename(name)[:180] + ".mp3"


def _options(dest: Path, *, quiet: bool, hooks: list[Callable[[dict[str, Any]], None]]) -> dict[str, Any]:
    """yt-dlp options for one track: best audio, 320 kbps MP3, tags and cover."""
    progress_hook, postprocessor_hook = hooks
    return ytdlp.options(
        dest,
        quiet=quiet,
        format="bestaudio/best",
        outtmpl=str(dest / "%(id)s.%(ext)s"),
        noplaylist=True,
        playlist_items="1",
        writethumbnail=True,
        progress_hooks=[progress_hook],
        postprocessor_hooks=[postprocessor_hook],
        postprocessors=[
            # JPEG cover: the format best supported in ID3 tags.
            {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"},
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": BITRATE_KBPS},
            {"key": "FFmpegMetadata", "add_metadata": True},
            {"key": "EmbedThumbnail"},
        ],
    )


def _finished_file(info: dict[str, Any], meta: spotify.SpotifyTrack | None) -> Path:
    """Renames the converted MP3 to "Artist - Title.mp3", with the Spotify tags when there are some."""
    if info.get("_type") in ("playlist", "multi_video"):
        info = next(e for e in info["entries"] if e)
    mp3 = Path(info["requested_downloads"][0]["filepath"])
    if meta is not None:
        spotify.write_tags(mp3, meta)
        name = _filename(meta.title, meta.artist)
    else:
        fields = describe(info)
        name = _filename(fields["title"], fields["artist"])
    return mp3.rename(mp3.with_name(name))


def download_mp3(
    track: Track,
    dest: Path,
    *,
    on_progress: Callable[..., None] = _noop,
    on_meta: Callable[[dict[str, Any]], None] = _noop,
    cancel: threading.Event | None = None,
    quiet: bool = True,
) -> Path:
    """Downloads `track` into `dest`, a folder of its own, and returns the path of the MP3.

    `on_progress(stage, fraction, speed, eta)` is called with the stages "matching" (Spotify),
    "downloading" and "converting". `on_meta(fields)` receives the track details as soon as
    they are known.
    """
    dest.mkdir(parents=True, exist_ok=True)

    def check_cancel(*_: object) -> None:
        if cancel is not None and cancel.is_set():
            raise Cancelled

    url, info, meta = track.url, track.info, None
    if track.spotify_id:
        on_progress("matching")
        meta = spotify.track_meta(track.spotify_id)
        url, info = spotify.find_on_youtube_music(meta), None
        check_cancel()

    def progress_hook(d: dict[str, Any]) -> None:
        check_cancel()
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            fraction = d["downloaded_bytes"] / total if total else None
            on_progress("downloading", fraction, d.get("speed"), d.get("eta"))

    def postprocessor_hook(d: dict[str, Any]) -> None:
        check_cancel()
        if d["status"] == "started" and d["postprocessor"] == "ExtractAudio":
            on_progress("converting")

    opts = _options(dest, quiet=quiet, hooks=[progress_hook, postprocessor_hook])
    with YoutubeDL(opts) as ydl:
        if info is None:
            on_progress("downloading")
            info = ydl.extract_info(url, download=False, process=False)
        if info.get("is_live"):
            raise UserError("live_not_supported", LIVE_NOT_SUPPORTED)
        if meta is None:
            on_meta(describe(info))
        check_cancel()
        info = ydl.process_ie_result(info, download=True)

    return _finished_file(info, meta)
