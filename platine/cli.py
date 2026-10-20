"""Command line: `platine download LINK...` and `platine serve`."""

import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Annotated, Any

import typer
import uvicorn
from rich.console import Console
from rich.markup import escape
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskID, TaskProgressColumn, TextColumn

from . import errors, sources
from .downloader import download_mp3
from .models import Track

app = typer.Typer(
    help="Paste a link, get a 320 kbps MP3: YouTube, YouTube Music, SoundCloud, Spotify, Bandcamp...",
    no_args_is_help=True,
    add_completion=False,
)
console = Console(stderr=True)

STAGES = {
    "matching": "searching YouTube Music",
    "downloading": "downloading",
    "converting": "converting to MP3",
}


def free_path(path: Path) -> Path:
    """`path`, or "name (2).mp3", "name (3).mp3"... when the file already exists."""
    candidate, n = path, 1
    while candidate.exists():
        n += 1
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
    return candidate


def _label(track: Track) -> str:
    name = " - ".join(part for part in (track.artist, track.title) if part) or track.url
    return escape(name if len(name) <= 60 else name[:59] + "…")


def _convert(track: Track, output: Path, progress: Progress, task: TaskID) -> bool:
    def on_progress(stage: str, fraction: float | None = None, _speed: object = None, _eta: object = None) -> None:
        progress.update(task, stage=STAGES.get(stage, stage), completed=fraction or 0)

    def on_meta(fields: dict[str, Any]) -> None:
        for name, value in fields.items():
            if value:
                setattr(track, name, value)
        progress.update(task, title=_label(track))

    with tempfile.TemporaryDirectory(prefix=".platine-", dir=output) as tmp:
        try:
            mp3 = download_mp3(track, Path(tmp), on_progress=on_progress, on_meta=on_meta)
        except Exception as exc:  # pylint: disable=broad-exception-caught  # one failed track must not stop the others
            progress.update(task, stage=f"[red]✗ {escape(errors.explain(exc).message)}[/]")
            return False
        final = Path(shutil.move(mp3, free_path(output / mp3.name)))
    progress.update(task, completed=1, stage=f"[green]✓[/] {escape(final.name)}")
    return True


@app.command()
def download(
    urls: Annotated[list[str], typer.Argument(metavar="LINK...", help="Tracks, videos, playlists or albums.")],
    output: Annotated[Path, typer.Option("--output", "-o", help="Destination folder.", file_okay=False)] = Path(),
    jobs: Annotated[int, typer.Option("--jobs", "-j", min=1, max=8, help="Conversions in parallel.")] = 3,
) -> None:
    """Download and convert to 320 kbps MP3, with title, artist and cover."""
    output.mkdir(parents=True, exist_ok=True)
    failed = 0
    tracks: list[Track] = []
    for url in urls:
        try:
            with console.status(f"Reading {escape(url)}..."):
                resolved = sources.resolve(url)
        except Exception as exc:  # pylint: disable=broad-exception-caught  # report it and go on with the next link
            console.print(f"[red]✗[/] {escape(url)}: {escape(errors.explain(exc).message)}")
            failed += 1
            continue
        if resolved.playlist:
            count = len(resolved.tracks)
            console.print(f"[bold]{escape(resolved.playlist)}[/]: {count} track{'s' if count > 1 else ''}")
        tracks += resolved.tracks

    columns = (
        SpinnerColumn(finished_text=" "),
        TextColumn("{task.fields[title]}", table_column=None),
        BarColumn(bar_width=24),
        TaskProgressColumn(),
        TextColumn("{task.fields[stage]}"),
    )
    with Progress(*columns, console=console) as progress, ThreadPoolExecutor(max_workers=jobs) as pool:
        tasks = [progress.add_task("", total=1, title=_label(t), stage="waiting") for t in tracks]
        results = list(
            pool.map(lambda pair: _convert(pair[0], output, progress, pair[1]), zip(tracks, tasks, strict=True))
        )
    failed += results.count(False)
    if failed:
        raise typer.Exit(code=1)


@app.command()
def serve(
    host: Annotated[str, typer.Option(help="Address to listen on (0.0.0.0 for the whole network).")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="Port to listen on.")] = 8320,
    reload: Annotated[bool, typer.Option(help="Reload on every code change (development).")] = False,
) -> None:
    """Start the web interface."""
    uvicorn.run("platine.web:app", host=host, port=port, reload=reload, proxy_headers=True)
