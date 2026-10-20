import pytest
from yt_dlp.utils import DownloadError

from platine.errors import Problem, UserError, explain, is_expected


@pytest.mark.parametrize(
    ("message", "code"),
    [
        ("ERROR: Unsupported URL: https://example.com/", "unsupported_site"),
        ("ERROR: 'abc' is not a valid URL.", "invalid_url"),
        ("ERROR: [youtube] abc: Video unavailable", "unavailable"),
        ("ERROR: [soundcloud] abc: This track is not available in your country", "unavailable"),
        ("ERROR: [youtube] abc: Private video. Sign in", "private"),
        ("ERROR: [youtube] abc: Sign in to confirm your age", "age_restricted"),
        ("ERROR: [youtube] abc: Sign in to confirm you're not a bot", "bot_check"),
        ("ERROR: [youtube] abc: This live event will begin in 3 hours", "live_not_started"),
        ("ERROR: This video is DRM protected", "drm"),
        ("ERROR: Unable to download webpage: HTTP Error 404: Not Found", "not_found"),
        ("ERROR: Unable to download webpage: HTTP Error 403: Forbidden", "forbidden"),
        ("ERROR: Unable to download webpage: <urlopen error timed out>", "unreachable"),
    ],
)
def test_known_ytdlp_errors_get_a_stable_code(message: str, code: str) -> None:
    problem = explain(DownloadError(message))
    assert problem.code == code
    assert problem.message and "ERROR" not in problem.message


def test_unknown_ytdlp_error_keeps_its_message_without_prefix_or_colors() -> None:
    problem = explain(DownloadError("\x1b[0;31mERROR:\x1b[0m [foo] bar: weird thing"))
    assert problem == Problem("download_failed", "[foo] bar: weird thing")


def test_user_error_keeps_its_code_and_message() -> None:
    assert explain(UserError("ytm_no_match", "Track not found on YouTube Music.")) == Problem(
        "ytm_no_match", "Track not found on YouTube Music."
    )


def test_bugs_get_a_generic_message_and_are_not_expected() -> None:
    exc = KeyError("requested_downloads")
    assert explain(exc) == Problem("unexpected", "Unexpected error during the conversion.")
    assert not is_expected(exc)
    assert is_expected(UserError("x", "y"))
    assert is_expected(DownloadError("x"))
