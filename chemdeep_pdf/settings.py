"""Runtime settings for the OA PDF downloader."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_root() -> Path:
    return Path(os.getenv("CHEM_PDF_ROOT", str(Path.home() / ".chemdeep-pdf")))


def _default_email() -> str:
    return (
        os.getenv("CHEM_PDF_UNPAYWALL_EMAIL")
        or os.getenv("UNPAYWALL_EMAIL")
        or ""
    )


@dataclass(frozen=True)
class Settings:
    """Configuration resolved from environment variables.

    Unpaywall requires a contact email on every request. Set
    ``CHEM_PDF_UNPAYWALL_EMAIL`` (or ``UNPAYWALL_EMAIL``) before running the
    downloader. The downloader raises a configuration error before calling
    Unpaywall when no email is configured.
    """

    root_dir: Path = field(default_factory=_default_root)
    unpaywall_email: str = field(default_factory=_default_email)
    unpaywall_api_base: str = os.getenv(
        "CHEM_PDF_UNPAYWALL_API_BASE",
        "https://api.unpaywall.org/v2",
    )
    request_timeout_seconds: float = float(
        os.getenv("CHEM_PDF_REQUEST_TIMEOUT_SECONDS", "30")
    )


settings = Settings()
