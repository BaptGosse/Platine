import logging
from pathlib import Path

import pytest

from platine import ytdlp


def test_quiet_mode_sends_ytdlp_messages_to_logging(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    logger = ytdlp.options(tmp_path)["logger"]
    with caplog.at_level(logging.DEBUG, logger="platine.yt-dlp"):
        logger.debug("[youtube] Extracting URL")
        logger.info("info")
        logger.warning("careful")
        logger.error("ERROR: broken")
    assert [r.levelname for r in caplog.records] == ["DEBUG", "INFO", "WARNING", "ERROR"]


def test_verbose_mode_lets_ytdlp_print_its_progress(tmp_path: Path) -> None:
    opts = ytdlp.options(tmp_path, quiet=False, format="bestaudio")
    assert "logger" not in opts
    assert (opts["quiet"], opts["noprogress"], opts["format"]) == (False, False, "bestaudio")
    assert "proxy" not in opts and "cookiefile" not in opts
