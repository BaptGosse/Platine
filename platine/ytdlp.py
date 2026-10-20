"""Shared yt-dlp options: proxy, cookies and logging."""

import logging
import shutil
from pathlib import Path
from typing import Any

from .config import settings

log = logging.getLogger("platine.yt-dlp")


class _Logger:
    """Sends yt-dlp messages to the logging module (and therefore to the container logs)."""

    def debug(self, msg: str) -> None:
        """Debug and progress messages."""
        log.debug(msg)

    def info(self, msg: str) -> None:
        """Informational messages."""
        log.info(msg)

    def warning(self, msg: str) -> None:
        """Warnings, such as a missing format."""
        log.warning(msg)

    def error(self, msg: str) -> None:
        """Errors; yt-dlp also raises them as exceptions."""
        log.error(msg)


def options(workdir: Path, *, quiet: bool = True, **extra: Any) -> dict[str, Any]:
    """yt-dlp options shared by every call, merged with `extra`. Cookies are copied into `workdir`."""
    opts: dict[str, Any] = {"quiet": quiet, "noprogress": quiet}
    if quiet:
        opts["logger"] = _Logger()
    if settings.proxy:
        opts["proxy"] = settings.proxy
    if settings.cookies_file:
        # yt-dlp rewrites the cookies file when it is done: give it a copy,
        # which also lets the original be mounted read-only.
        workdir.mkdir(parents=True, exist_ok=True)
        copy = workdir / "cookies.txt"
        shutil.copyfile(settings.cookies_file, copy)
        opts["cookiefile"] = str(copy)
    return opts | extra
