"""Unit tests for the pure helpers in ``chemdeep_pdf.downloader``.

These tests exercise the offline logic — DOI sanitation, PDF validity,
PMC URL detection, and OA-package PDF selection — without hitting the
network.
"""

from __future__ import annotations

import io
import sys
import tarfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chemdeep_pdf.downloader import (  # noqa: E402
    _build_unpaywall_api_url,
    _candidate_http_urls_for_ftp_href,
    _extract_pdf_from_tgz_bytes,
    _is_pmc_host_url,
    _normalize_pmcid,
    _primary_pdf_sort_key,
    _sanitize_doi,
    _write_pdf_if_valid,
)
import chemdeep_pdf.downloader as downloader  # noqa: E402


class TestSanitizeDoi:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("10.1021/jacs.3c00001", "10.1021/jacs.3c00001"),
            ("https://doi.org/10.1021/jacs.3c00001", "10.1021/jacs.3c00001"),
            ("doi/10.1021/jacs.3c00001", "10.1021/jacs.3c00001"),
            ("pdf/10.1021/jacs.3c00001", "10.1021/jacs.3c00001"),
            ("10.1021/jacs.3c00001.s001", "10.1021/jacs.3c00001"),
            ("  10.1021/jacs.3c00001  ", "10.1021/jacs.3c00001"),
        ],
    )
    def test_sanitizes_common_variants(self, raw: str, expected: str) -> None:
        assert _sanitize_doi(raw) == expected

    def test_empty_input(self) -> None:
        assert _sanitize_doi("") == ""
        assert _sanitize_doi("   ") == ""


class TestNormalizePmcid:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("PMC123456", "PMC123456"),
            ("pmc123456", "PMC123456"),
            ("  PMC123456  ", "PMC123456"),
            ("Europe PMC record PMC987654", "PMC987654"),
            ("", ""),
        ],
    )
    def test_normalizes(self, raw: str, expected: str) -> None:
        assert _normalize_pmcid(raw) == expected


class TestIsPmcHostUrl:
    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://pmc.ncbi.nlm.nih.gov/articles/PMC123", True),
            ("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC123", True),
            ("https://europepmc.org/article/MED/12345", False),
            ("https://example.com/paper.pdf", False),
            ("", False),
        ],
    )
    def test_detects_pmc_webpages(self, url: str, expected: bool) -> None:
        assert _is_pmc_host_url(url) is expected


class TestFtpToHttpCandidates:
    def test_rewrites_ftp_oa_package_urls(self) -> None:
        candidates = _candidate_http_urls_for_ftp_href(
            "ftp://ftp.ncbi.nlm.nih.gov/pub/pmc/oa_package/00/01/PMC123.tar.gz"
        )
        assert candidates[0].startswith("https://ftp.ncbi.nlm.nih.gov")
        assert any("/deprecated/" in url for url in candidates)

    def test_ignores_non_ncbi_ftp(self) -> None:
        assert _candidate_http_urls_for_ftp_href("ftp://example.com/x.pdf") == []


class TestPrimaryPdfSortKey:
    def test_penalises_supplementary_filenames(self) -> None:
        primary = _primary_pdf_sort_key("main.pdf")
        supplement = _primary_pdf_sort_key("supplement_01.pdf")
        assert primary < supplement


class TestWritePdfIfValid:
    def test_rejects_non_pdf_bytes(self, tmp_path: Path) -> None:
        target = tmp_path / "paper.pdf"
        result = _write_pdf_if_valid(target, b"<html>access denied</html>")
        assert result is None
        assert not target.exists()

    def test_accepts_pdf_signature(self, tmp_path: Path) -> None:
        target = tmp_path / "paper.pdf"
        result = _write_pdf_if_valid(target, b"%PDF-1.7\nstub")
        assert result == str(target)
        assert target.read_bytes().startswith(b"%PDF-")


class TestUnpaywallEmail:
    def test_requires_contact_email(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            downloader,
            "settings",
            type("SettingsStub", (), {
                "unpaywall_email": "",
                "unpaywall_api_base": "https://api.unpaywall.org/v2",
            })(),
        )
        with pytest.raises(ValueError, match="CHEM_PDF_UNPAYWALL_EMAIL"):
            _build_unpaywall_api_url("10.1/example")


class TestExtractPdfFromTgz:
    def _make_archive(self, members: dict[str, bytes]) -> bytes:
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
            for name, payload in members.items():
                info = tarfile.TarInfo(name=name)
                info.size = len(payload)
                tar.addfile(info, io.BytesIO(payload))
        return buffer.getvalue()

    def test_prefers_primary_over_supplement(self, tmp_path: Path) -> None:
        archive = self._make_archive({
            "package/supplement.pdf": b"%PDF-1.4\nsupplement",
            "package/main.pdf": b"%PDF-1.4\nmain",
        })
        target = tmp_path / "paper.pdf"
        saved, member = _extract_pdf_from_tgz_bytes(archive, target)
        assert saved == str(target)
        assert "main" in member

    def test_reports_when_no_pdf(self, tmp_path: Path) -> None:
        archive = self._make_archive({"readme.txt": b"hello"})
        target = tmp_path / "paper.pdf"
        saved, detail = _extract_pdf_from_tgz_bytes(archive, target)
        assert saved is None
        assert "did not contain" in detail.lower()
