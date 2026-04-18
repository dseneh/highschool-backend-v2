"""
Download the free MaxMind GeoLite2-City database.

Usage::

    python manage.py download_geoip_db --license-key YOUR_KEY

Get a free license key at https://www.maxmind.com/en/geolite2/signup
"""

import io
import tarfile
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

DEFAULT_DEST = Path(settings.BASE_DIR) / "geoip"

DOWNLOAD_URL = (
    "https://download.maxmind.com/app/geoip_download"
    "?edition_id=GeoLite2-City&license_key={key}&suffix=tar.gz"
)


class Command(BaseCommand):
    help = "Download the free MaxMind GeoLite2-City database for IP geolocation."

    def add_arguments(self, parser):
        parser.add_argument(
            "--license-key",
            required=True,
            help="Your MaxMind license key (free at maxmind.com/en/geolite2/signup).",
        )
        parser.add_argument(
            "--dest",
            default=str(DEFAULT_DEST),
            help=f"Destination directory (default: {DEFAULT_DEST}).",
        )

    def handle(self, *args, **options):
        key = options["license_key"]
        dest = Path(options["dest"])
        dest.mkdir(parents=True, exist_ok=True)

        url = DOWNLOAD_URL.format(key=key)
        self.stdout.write(f"Downloading GeoLite2-City from MaxMind…")

        try:
            response = urllib.request.urlopen(url)  # noqa: S310
            data = response.read()
        except Exception as exc:
            self.stderr.write(self.style.ERROR(f"Download failed: {exc}"))
            return

        # Extract the .mmdb file from the tar.gz archive
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith(".mmdb"):
                    member.name = Path(member.name).name  # flatten path
                    tar.extract(member, path=str(dest))
                    final_path = dest / member.name
                    self.stdout.write(
                        self.style.SUCCESS(f"Saved to {final_path} ({final_path.stat().st_size / 1024 / 1024:.1f} MB)")
                    )
                    return

        self.stderr.write(self.style.ERROR("No .mmdb file found in the archive."))
