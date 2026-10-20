"""Real conversions from the Internet. Slow and dependent on the sites: `make test-network`."""

from pathlib import Path

import pytest
from mutagen.id3 import ID3
from mutagen.mp3 import MP3

from platine import sources
from platine.downloader import download_mp3

pytestmark = pytest.mark.network


@pytest.mark.parametrize(
    ("url", "title"),
    [
        ("https://www.youtube.com/watch?v=jNQXAC9IVRw", "Me at the zoo"),
        ("https://soundcloud.com/forss/flickermood", "Flickermood"),
        ("https://open.spotify.com/track/0DiWol3AO6WpXZgp0goxAV", "One More Time"),
    ],
)
def test_real_conversion_is_a_tagged_320_kbps_mp3(url: str, title: str, tmp_path: Path) -> None:
    [track] = sources.resolve(url).tracks
    mp3 = download_mp3(track, tmp_path)
    assert MP3(mp3).info.bitrate == 320_000  # pylint: disable=no-member  # set dynamically by mutagen
    tags = ID3(mp3)
    assert title in str(tags["TIT2"])
    assert tags.getall("APIC"), "missing cover"
