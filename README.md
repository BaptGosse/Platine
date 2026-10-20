<p align="center">
  <img src="platine/static/brand/logo.svg" alt="Platine" width="440">
</p>

<p align="center"><b>Paste a link, get the MP3.</b><br>
YouTube, YouTube Music, SoundCloud, Spotify, Bandcamp and hundreds of other sites,
as 320 kbps MP3 files with title, artist, album and cover.</p>

<p align="center">
  <a href="https://github.com/BaptGosse/Platine/actions/workflows/ci.yml"><img src="https://github.com/BaptGosse/Platine/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://baptgosse.github.io/Platine/python/html/"><img src="https://baptgosse.github.io/Platine/badges/python.svg" alt="Python coverage"></a>
  <a href="https://baptgosse.github.io/Platine/js/html/"><img src="https://baptgosse.github.io/Platine/badges/js.svg" alt="JavaScript coverage"></a>
  <img src="https://img.shields.io/badge/pylint-10.00%2F10-brightgreen" alt="Pylint 10/10">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license"></a>
</p>

<p align="center">
  <img src="platine/static/brand/screenshot-wide.png" alt="A playlist being converted in Platine" width="760">
</p>

## Features

- **One link is enough**: paste it and the conversion starts. Several links at once, drag and drop, a bookmarklet
  and Android sharing (once the app is installed) work too.
- **Playlists and albums** are split into tracks, converted in parallel and downloadable as one zip.
- **Spotify**: its audio is DRM-protected and cannot be downloaded. Platine reads the track details on Spotify,
  finds the same recording on YouTube Music (title, artists, duration and album are compared), then writes the
  Spotify tags and cover into the MP3.
- **Live progress**: every track is a record that spins while it converts, with its progress drawn around it.
  Cancel, retry and remove work track by track, and the list survives a reload.
- **French and English** interface, switchable at any time.
- **Installable app (PWA)**: home screen icon, interface available offline, update offered when a new version is deployed.
- **Command line**: `platine download LINK...` with progress bars.
- **Production ready**: non-root read-only container, Helm chart, Prometheus metrics, optional password,
  cookies and proxy for picky sites.

## Stack

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/yt--dlp-FF0000?style=for-the-badge&logo=youtube&logoColor=white" alt="yt-dlp">
  <img src="https://img.shields.io/badge/FFmpeg-007808?style=for-the-badge&logo=ffmpeg&logoColor=white" alt="FFmpeg">
  <img src="https://img.shields.io/badge/Alpine.js-8BC0D0?style=for-the-badge&logo=alpinedotjs&logoColor=black" alt="Alpine.js">
  <img src="https://img.shields.io/badge/i18next-26A69A?style=for-the-badge&logo=i18next&logoColor=white" alt="i18next">
  <img src="https://img.shields.io/badge/Workbox-PWA-5A0FC8?style=for-the-badge&logo=pwa&logoColor=white" alt="Workbox">
  <img src="https://img.shields.io/badge/uv-DE5FE9?style=for-the-badge&logo=uv&logoColor=white" alt="uv">
  <img src="https://img.shields.io/badge/Podman-892CA0?style=for-the-badge&logo=podman&logoColor=white" alt="Podman">
  <img src="https://img.shields.io/badge/Helm-0F1689?style=for-the-badge&logo=helm&logoColor=white" alt="Helm">
</p>

### Download and conversion

| | Tool | Role in Platine | License |
| --- | --- | --- | --- |
| 🎬 | [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Reads links and downloads the best audio from 1,800+ sites | Unlicense |
| 🎚️ | [FFmpeg](https://ffmpeg.org) | Encodes the 320 kbps MP3, embeds tags and cover | LGPL-2.1+ / GPL-2.0+ |
| 🦕 | [Deno](https://deno.com) | JavaScript runtime yt-dlp needs to read YouTube | MIT |
| 🟢 | [spotifyscraper](https://github.com/AliAkhtari78/SpotifyScraper) | Spotify track, album and playlist details, without an API key | MIT |
| 🔎 | [ytmusicapi](https://github.com/sigma67/ytmusicapi) | Finds the matching recording on YouTube Music | MIT |
| 🏷️ | [mutagen](https://github.com/quodlibet/mutagen) | Writes the Spotify ID3 tags and cover | GPL-2.0-or-later |
| 🌐 | [Requests](https://github.com/psf/requests) | HTTP with retries for covers and YouTube Music | Apache-2.0 |

### Server and command line

| | Tool | Role in Platine | License |
| --- | --- | --- | --- |
| ⚡ | [FastAPI](https://github.com/fastapi/fastapi) | HTTP API, static files and the generated service worker | MIT |
| 🦄 | [Uvicorn](https://github.com/encode/uvicorn) | ASGI server | BSD-3-Clause |
| 🧾 | [Pydantic](https://github.com/pydantic/pydantic) + [pydantic-settings](https://github.com/pydantic/pydantic-settings) | API models and `PLATINE_*` settings | MIT |
| 📈 | [prometheus-fastapi-instrumentator](https://github.com/trallnag/prometheus-fastapi-instrumentator) + [client_python](https://github.com/prometheus/client_python) | `/metrics` endpoint and conversion metrics | ISC / Apache-2.0 |
| ⌨️ | [Typer](https://github.com/fastapi/typer) | `platine download` and `platine serve` commands | MIT |
| 🌈 | [Rich](https://github.com/Textualize/rich) | Progress bars in the terminal | MIT |

### Interface

| | Tool | Role in Platine | License |
| --- | --- | --- | --- |
| 🏔️ | [Alpine.js](https://alpinejs.dev) + [Persist](https://alpinejs.dev/plugins/persist) | Reactive interface, track list kept across reloads | MIT |
| 🗣️ | [i18next](https://www.i18next.com) + [language detector](https://github.com/i18next/i18next-browser-languageDetector) | French and English translations | MIT |
| 📦 | [Workbox](https://developer.chrome.com/docs/workbox) | Service worker: offline interface, updates, cover cache | MIT |
| ✳️ | [Bootstrap Icons](https://icons.getbootstrap.com) | Icons | MIT |
| 🔤 | [Archivo](https://github.com/Omnibus-Type/Archivo) via [Fontsource](https://fontsource.org/fonts/archivo) | Variable typeface (width and weight) | OFL-1.1 |

Every frontend library is vendored in `platine/static/vendor/` with its license: no CDN, no build step.

### Quality

| | Tool | Role in Platine | License |
| --- | --- | --- | --- |
| 🧪 | [pytest](https://github.com/pytest-dev/pytest) + [pytest-cov](https://github.com/pytest-dev/pytest-cov) / [coverage.py](https://github.com/coveragepy/coveragepy) | Python tests, 100 % line and branch coverage required | MIT / Apache-2.0 |
| 🦕 | [Deno test](https://docs.deno.com/runtime/fundamentals/testing/) | Frontend tests and coverage, no Node needed | MIT |
| 🧹 | [Ruff](https://github.com/astral-sh/ruff) | Lint and formatting | MIT |
| 🔍 | [Pylint](https://github.com/pylint-dev/pylint) + [per-file-ignores](https://github.com/SAP/pylint-per-file-ignores) | Deeper static analysis, 10/10 | GPL-2.0-or-later / MIT |
| 🧷 | [mypy](https://github.com/python/mypy) | Static typing | MIT |
| 🎭 | [Responses](https://github.com/getsentry/responses), [HTTPX2](https://github.com/pydantic/httpx2) | Fake HTTP for tests, FastAPI test client | Apache-2.0 / BSD-3-Clause |
| 🏅 | [genbadge](https://github.com/smarie/python-genbadge) + [lcov-cobertura](https://github.com/eriwen/lcov-to-cobertura-xml) | Coverage badges published to GitHub Pages | BSD-3-Clause / Apache-2.0 |
| 🪝 | [pre-commit](https://pre-commit.com) | Same checks before each commit | MIT |

### Delivery

| | Tool | Role in Platine | License |
| --- | --- | --- | --- |
| ⚙️ | [uv](https://github.com/astral-sh/uv) | Dependencies and lock file | MIT / Apache-2.0 |
| 🦭 | [Podman](https://podman.io) / [Docker](https://www.docker.com) | Container image and compose | Apache-2.0 |
| ☸️ | [Helm](https://helm.sh) + [Kubernetes](https://kubernetes.io) | Chart with Ingress or Gateway API, NetworkPolicy, ServiceMonitor | Apache-2.0 |
| ✅ | [kubeconform](https://github.com/yannh/kubeconform) | Validates the rendered manifests in CI | Apache-2.0 |
| 🚀 | [GitHub Actions](https://github.com/features/actions) + [Dependabot](https://docs.github.com/code-security/dependabot) | CI, image and chart publishing, weekly yt-dlp updates | |

## Getting started

### With Podman or Docker

```bash
make up                 # podman compose up -d --build
```

Then open <http://localhost:8320>. `make down` stops it and `make logs` follows the logs.
With Docker: `make up CONTAINER=docker`, or directly `docker compose up -d --build`.

> Without the Makefile, Podman needs one setting when docker-compose is installed:
> `PODMAN_COMPOSE_PROVIDER=podman-compose podman compose up -d --build`
> (or enable the socket: `systemctl --user enable --now podman.socket`).

### Locally, for development

You need Python 3.12+, FFmpeg (`sudo dnf install ffmpeg`) and [uv](https://docs.astral.sh/uv/).
Without uv: `python3 -m venv .venv && .venv/bin/pip install uv`.

```bash
make install            # dependencies in .venv (uv sync)
make dev                # server with auto-reload on http://localhost:8320
```

### Command line

```bash
uv run platine download "https://www.youtube.com/watch?v=..." "https://open.spotify.com/album/..." -o ~/Music
uv run platine serve --host 0.0.0.0     # the web interface, without the Makefile
```

## Installing the app (PWA)

Browsers offer "Install the app" (button at the top right of the page) as soon as Platine is served over
**HTTPS** or on **localhost**: browsers only allow service workers there. Over plain HTTP on a local network,
the interface works but cannot be installed.

Once installed on Android, Platine appears in the **Share** menu of YouTube, SoundCloud, Spotify...:
sharing a track starts its conversion right away.

On a computer, the "Convert with Platine" bookmarklet at the bottom of the page can be dragged to the bookmarks bar:
one click from any music or video page sends it to Platine.

## Kubernetes

The chart lives in [`charts/platine`](charts/platine/README.md). To push the image and install it:

```bash
make push TAG=2.0.0             # ghcr.io/baptgosse/platine:2.0.0
make helm-install TAG=2.0.0
```

The chart offers an Ingress or an HTTPRoute (Gateway API), a NetworkPolicy that blocks internal addresses
(Platine downloads arbitrary links), a ServiceMonitor, and authentication and cookies from Secrets.
Conversions are kept in memory: stay at **one replica**.

## Settings

Every variable is optional.

| Variable | Default | Role |
| --- | --- | --- |
| `PLATINE_MAX_CONCURRENT` | `3` | Conversions running in parallel |
| `PLATINE_FILE_TTL` | `3600` | Seconds a finished MP3 stays downloadable |
| `PLATINE_MAX_PLAYLIST_ITEMS` | `100` | Maximum tracks kept per playlist or album |
| `PLATINE_MAX_QUEUED` | `500` | Waiting conversions beyond which Platine answers "try again later" |
| `PLATINE_AUTH_PASSWORD` | | Turns on a password (HTTP Basic) for everything except `/healthz` and `/metrics` |
| `PLATINE_AUTH_USERNAME` | `platine` | Matching user name |
| `PLATINE_COOKIES_FILE` | | `cookies.txt` file (Netscape format) for content that requires being signed in |
| `PLATINE_PROXY` | | HTTP(S) proxy for every outgoing request |
| `PLATINE_WORKDIR` | `/tmp/platine` | Work folder for conversions |

YouTube sometimes blocks servers hosted by cloud providers with a bot check. Cookies exported from a signed-in
browser, or a proxy, solve it.

## Code quality

```bash
make check              # ruff, pylint, mypy, Python and JS tests with 100 % coverage gates, helm lint
make coverage           # HTML reports and badges in coverage/
make test-network       # real YouTube, SoundCloud and Spotify conversions (slow)
make fmt                # fixes the style
```

- **Python**: 103 unit tests, 100 % of lines, functions and branches. yt-dlp, Spotify and YouTube Music are faked,
  so no network access is needed. Ruff, Pylint (10/10) and mypy all pass.
- **Interface**: 45 tests run with `deno test` on the application logic (`lib.js`, `component.js`, `i18n.js`),
  100 % covered, plus checks that the French and English translations have the same keys.
  `main.js` (browser bootstrap) and `sw.js` (service worker) are checked in a real browser instead.
- **CI**: every push runs all of the above, validates the chart with kubeconform, publishes the coverage reports
  to <https://baptgosse.github.io/Platine/>, pushes the image to GHCR from `main`, and publishes the chart as
  an OCI artifact on each `v*` tag.

### When a site breaks

YouTube and the others change how they work regularly, and yt-dlp follows.

```bash
make update-ytdlp && make up
```

Dependabot also proposes the update every week.

## About audio quality

YouTube does not stream audio at 320 kbps: its best track is around 130 to 160 kbps (Opus), and SoundCloud
streams at 128 kbps. The MP3 really is encoded at 320 kbps, but that only avoids losing quality during the
conversion. It cannot bring back details missing from the source.

## Project layout

```
platine/            Python code: API, conversions, Spotify, command line
  static/           interface: HTML, CSS, JS, locales, service worker, logo, vendored libraries
tests/              Python tests, and tests/js for the interface
scripts/            coverage gate used by make and CI
charts/platine/     Helm chart
Dockerfile, compose.yaml, Makefile, .github/
```

## License

Platine is released under the [MIT license](LICENSE). The container image also ships FFmpeg and mutagen,
which keep their own GPL licenses, and the vendored frontend libraries keep theirs (see `platine/static/vendor/`).
