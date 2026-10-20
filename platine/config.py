"""Settings, read from the PLATINE_* environment variables."""

import tempfile
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Every setting, with its default value."""

    # An empty variable (e.g. PLATINE_PROXY="" in a ConfigMap) counts as unset.
    model_config = SettingsConfigDict(env_prefix="PLATINE_", env_ignore_empty=True)

    max_concurrent: int = 3
    """Conversions running in parallel."""
    file_ttl: int = 3600
    """How long, in seconds, a finished MP3 stays downloadable."""
    max_playlist_items: int = 100
    max_queued: int = 500
    """Waiting or running conversions beyond which new requests are refused."""
    workdir: Path = Path(tempfile.gettempdir()) / "platine"
    cookies_file: Path | None = None
    """cookies.txt file (Netscape format) for content that requires being signed in."""
    proxy: str | None = None
    auth_username: str = "platine"
    auth_password: str | None = None
    """Turns on HTTP Basic authentication as soon as it is set."""


settings = Settings()
