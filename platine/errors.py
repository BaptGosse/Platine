"""Readable errors. Each one has a stable code that the web interface translates, plus an English message."""

import re
from dataclasses import dataclass

from yt_dlp.utils import DownloadError


class UserError(Exception):
    """An error whose cause is known and can be shown to the user as is."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Problem:
    """What went wrong: a stable `code` for the interface and an English `message`."""

    code: str
    message: str


LIVE_NOT_SUPPORTED = "Live streams are not supported: wait until the broadcast ends."

ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")

# Fragments of the most common yt-dlp messages, from the most specific to the most general.
KNOWN_ERRORS = [
    ("Unsupported URL", "unsupported_site", "This site is not supported, or the page has no audio or video."),
    ("is not a valid URL", "invalid_url", "This link is not valid."),
    ("DRM", "drm", "This media is DRM-protected and cannot be downloaded."),
    ("Private video", "private", "This video is private."),
    (
        "confirm your age",
        "age_restricted",
        "This media is age-restricted. Add cookies from a signed-in account (see the README).",
    ),
    (
        "not a bot",
        "bot_check",
        "YouTube is blocking this server with a bot check. Add cookies or a proxy (see the README).",
    ),
    ("live event will begin", "live_not_started", "This live stream has not started yet."),
    ("unavailable", "unavailable", "This media is unavailable: removed, private or blocked in this country."),
    ("not available", "unavailable", "This media is unavailable: removed, private or blocked in this country."),
    ("HTTP Error 404", "not_found", "Page not found (error 404). Check the link."),
    ("HTTP Error 403", "forbidden", "The site refused access (error 403)."),
    ("Unable to download webpage", "unreachable", "Could not reach the page. Check the link and try again."),
]


def explain(exc: BaseException) -> Problem:
    """Turns any exception into a `Problem` the user can understand."""
    if isinstance(exc, UserError):
        return Problem(exc.code, str(exc))
    message = ANSI_ESCAPE.sub("", str(exc)).removeprefix("ERROR: ")
    lowered = message.lower()
    for needle, code, text in KNOWN_ERRORS:
        if needle.lower() in lowered:
            return Problem(code, text)
    if isinstance(exc, DownloadError):
        return Problem("download_failed", message)
    return Problem("unexpected", "Unexpected error during the conversion.")


def is_expected(exc: BaseException) -> bool:
    """False for actual bugs, which deserve a full traceback in the logs."""
    return isinstance(exc, (UserError, DownloadError))
