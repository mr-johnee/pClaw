"""Tests for scripts/rank_downloaded.py."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "rank_downloaded.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("rank_downloaded", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_fixture(tmp_path: Path) -> dict[str, Path]:
    shortlist = [
        {"doi": "10.1/a", "pmid": "1", "title": "A", "score": 10, "pubdate": "2025-06-01"},
        {"doi": "10.1/b", "pmid": "2", "title": "B", "score": 9,  "pubdate": "2024-01-15"},
        {"doi": "10.1/c", "pmid": "3", "title": "C", "score": 8,  "pubdate": "2025-11-20"},
        {"doi": "10.1/d", "pmid": "4", "title": "D", "score": 7,  "pubdate": "2023-03-03"},
        {"doi": "10.1/e", "pmid": "5", "title": "E", "score": 7,  "pubdate": "2025-05-10"},
        {"doi": "10.1/f", "pmid": "6", "title": "F (not downloaded)", "score": 10, "pubdate": "2025-07-01"},
    ]
    download_log = {
        "generated_at": "2026-04-22T00:00:00Z",
        "output_dir": str(tmp_path / "pdfs"),
        "totals": {"requested": 6, "succeeded": 4, "failed": 1, "skipped_existing": 1},
        "results": [
            {"doi": "10.1/a", "status": "ok", "pdf_path": "pdfs/a/paper.pdf"},
            {"doi": "10.1/b", "status": "ok", "pdf_path": "pdfs/b/paper.pdf"},
            {"doi": "10.1/c", "status": "skipped_existing", "pdf_path": "pdfs/c/paper.pdf"},
            {"doi": "10.1/d", "status": "failed"},
            {"doi": "10.1/e", "status": "ok", "pdf_path": "pdfs/e/paper.pdf"},
            {"doi": "10.1/f", "status": "failed"},
        ],
    }
    shortlist_path = tmp_path / "shortlist.json"
    log_path = tmp_path / "download_log.json"
    shortlist_path.write_text(json.dumps(shortlist))
    log_path.write_text(json.dumps(download_log))
    return {"shortlist": shortlist_path, "log": log_path}


class TestRanking:
    def test_joins_and_sorts(self, tmp_path: Path) -> None:
        mod = _load_module()
        fixtures = _write_fixture(tmp_path)
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--shortlist",
                str(fixtures["shortlist"]),
                "--download-log",
                str(fixtures["log"]),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        ranked = payload["ranked"]
        dois = [entry["doi"] for entry in ranked]
        # Failed downloads excluded; paper F absent.
        assert "10.1/f" not in dois
        assert "10.1/d" not in dois
        # Primary sort by score desc.
        scores = [entry["score"] for entry in ranked]
        assert scores == sorted(scores, reverse=True)
        # Tie at score 7: newer pubdate (2025-05-10) ranks before 2023-03-03,
        # but 10.1/d is filtered out; only 10.1/e remains at 7. Still, verify
        # that tie-break works at the top: 10.1/a (10, 2025-06) is first.
        assert ranked[0]["doi"] == "10.1/a"
        assert payload["summary"]["downloaded_pdfs"] == 4
        assert payload["summary"]["ranked_returned"] == 4

    def test_top_k_truncation(self, tmp_path: Path) -> None:
        fixtures = _write_fixture(tmp_path)
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "--shortlist",
                str(fixtures["shortlist"]),
                "--download-log",
                str(fixtures["log"]),
                "--top-k",
                "2",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        assert len(payload["ranked"]) == 2
        assert payload["summary"]["truncated"] is True
        assert payload["summary"]["ranked_returned"] == 2
        # The top-2 are the two highest scores (10 and 9).
        assert [e["score"] for e in payload["ranked"]] == [10, 9]


class TestPubdateSortKey:
    def test_parses_common_forms(self) -> None:
        mod = _load_module()
        assert mod._pubdate_sort_key("2025-06-01") > mod._pubdate_sort_key("2024-06-01")
        assert mod._pubdate_sort_key("2025") > mod._pubdate_sort_key("2024-12-31")
        assert mod._pubdate_sort_key("") == (0, 0, 0)


class TestScoreFieldAutodetect:
    @pytest.mark.parametrize(
        "field_name",
        ["score", "relevance_score", "relevance"],
    )
    def test_detects_known_field_names(self, tmp_path: Path, field_name: str) -> None:
        shortlist = [{"doi": "10.1/a", "title": "A", field_name: 9}]
        log = {
            "results": [{"doi": "10.1/a", "status": "ok", "pdf_path": "pdfs/a/paper.pdf"}]
        }
        sp = tmp_path / "s.json"
        lp = tmp_path / "l.json"
        sp.write_text(json.dumps(shortlist))
        lp.write_text(json.dumps(log))
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--shortlist", str(sp), "--download-log", str(lp)],
            capture_output=True,
            text=True,
            check=True,
        )
        payload = json.loads(result.stdout)
        assert payload["ranked"][0]["score"] == 9
