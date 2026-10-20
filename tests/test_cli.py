import runpy
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from platine import cli
from platine.errors import UserError
from platine.models import Resolved, Track

runner = CliRunner()


def fake_resolve(url: str) -> Resolved:
    if "playlist" in url:
        return Resolved(
            [Track(url=f"{url}#{n}", source="YouTube", title=f"Track {n}") for n in (1, 2)], playlist="Album"
        )
    if "single" in url:
        return Resolved([Track(url=url, source="YouTube", title="Lone")], playlist="Single")
    if "broken" in url:
        raise UserError("unsupported_site", "This site is not supported.")
    return Resolved([Track(url=url, source="YouTube", title="Alone")])


def fake_download(track: Track, dest: Path, *, on_progress: Any, on_meta: Any, **kwargs: Any) -> Path:
    on_progress("downloading", 0.5)
    on_meta({"artist": "Artist", "album": None})
    if track.title == "Track 2":
        raise UserError("ytm_no_match", "Track not found on YouTube Music.")
    mp3 = dest / f"{track.title}.mp3"
    mp3.write_bytes(b"mp3")
    return mp3


@pytest.fixture(autouse=True)
def fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli.sources, "resolve", fake_resolve)
    monkeypatch.setattr(cli, "download_mp3", fake_download)


def test_download_writes_files_and_never_overwrites(tmp_path: Path) -> None:
    (tmp_path / "Alone.mp3").write_bytes(b"old")
    result = runner.invoke(cli.app, ["download", "https://youtu.be/x", "-o", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "Alone.mp3").read_bytes() == b"old"
    assert (tmp_path / "Alone (2).mp3").read_bytes() == b"mp3"
    assert not list(tmp_path.glob(".platine-*"))  # temporary folders cleaned up


def test_failures_are_reported_and_set_the_exit_code(tmp_path: Path) -> None:
    result = runner.invoke(
        cli.app,
        [
            "download",
            "https://broken.example",
            "https://youtube.com/playlist?list=x",
            "https://y.t/single",
            "-o",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 1
    assert "This site is not supported." in result.output
    assert "Album: 2 tracks" in result.output
    assert "Single: 1 track" in result.output
    assert "Track not found on YouTube Music." in result.output
    assert sorted(p.name for p in tmp_path.glob("*.mp3")) == ["Lone.mp3", "Track 1.mp3"]


def test_long_names_are_shortened() -> None:
    track = Track(url="https://youtu.be/x", source="YouTube", artist="A" * 40, title="B" * 40)
    assert len(cli._label(track)) == 60
    assert cli._label(Track(url="https://youtu.be/x", source="YouTube")) == "https://youtu.be/x"


def test_free_path(tmp_path: Path) -> None:
    target = tmp_path / "a.mp3"
    assert cli.free_path(target) == target
    target.touch()
    (tmp_path / "a (2).mp3").touch()
    assert cli.free_path(target) == tmp_path / "a (3).mp3"


def test_serve_starts_uvicorn(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: calls.append((app, kwargs)))
    result = runner.invoke(cli.app, ["serve", "--host", "10.0.0.2", "--port", "9000"])
    assert result.exit_code == 0, result.output
    assert calls == [("platine.web:app", {"host": "10.0.0.2", "port": 9000, "reload": False, "proxy_headers": True})]


def test_help_lists_both_commands() -> None:
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert "download" in result.output and "serve" in result.output


def test_python_dash_m_runs_the_cli(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["platine", "--help"])
    with pytest.raises(SystemExit) as exited:
        runpy.run_module("platine", run_name="__main__")
    assert exited.value.code == 0
    assert "Paste a link" in capsys.readouterr().out
