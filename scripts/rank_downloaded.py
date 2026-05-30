#!/usr/bin/env python3
"""Rank successfully downloaded papers by relevance score for Step 5a budgeting.

After Step 4 runs, the intersection of the shortlist with actually-acquired
PDFs is the real extraction universe. This utility joins ``shortlist.json``
against ``pdfs/download_log.json`` (and optionally ``pubmed_results.json``
for publication-date tie-breaks), sorts the surviving papers by their
relevance score (descending), and emits both a machine-readable JSON ranking
on stdout and a human-readable summary on stderr so that the caller can show a
budget prompt to the user before committing to a run of the structure-
extraction prompt.

Typical invocation in a run directory::

    python3 scripts/rank_downloaded.py \\
        --shortlist shortlist.json \\
        --download-log pdfs/download_log.json \\
        --pubmed-results pubmed_results.json \\
        --pretty

Optional ``--top-k N`` truncates the ranked list in place.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


SCORE_FIELD_CANDIDATES = (
    "score",
    "relevance_score",
    "relevance",
)

DOWNLOADED_STATUSES = frozenset({"ok", "skipped_existing"})


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _normalize_doi(value: Any) -> str:
    return str(value or "").strip().lower()


def _coerce_shortlist(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return [entry for entry in data if isinstance(entry, dict)]
    if isinstance(data, dict):
        for key in ("shortlist", "articles", "items", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [entry for entry in value if isinstance(entry, dict)]
    raise ValueError(
        "Unsupported shortlist shape; expected a JSON array or an object with "
        "a 'shortlist' / 'articles' / 'items' / 'data' array."
    )


def _coerce_download_results(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        results = data.get("results")
        if isinstance(results, list):
            return [entry for entry in results if isinstance(entry, dict)]
    if isinstance(data, list):
        return [entry for entry in data if isinstance(entry, dict)]
    raise ValueError(
        "Unsupported download log shape; expected a dict with a 'results' "
        "array or a bare JSON array of result entries."
    )


def _coerce_pubmed(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict):
        articles = data.get("articles")
        if isinstance(articles, list):
            return [entry for entry in articles if isinstance(entry, dict)]
    if isinstance(data, list):
        return [entry for entry in data if isinstance(entry, dict)]
    return []


def _pick_score(entry: dict[str, Any], explicit_field: str | None) -> float | None:
    fields = (explicit_field,) if explicit_field else SCORE_FIELD_CANDIDATES
    for field in fields:
        if not field:
            continue
        value = entry.get(field)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _pubdate_sort_key(pubdate: str) -> tuple[int, int, int]:
    """Best-effort parse of a pubdate string into a comparable tuple.

    PubMed pubdates are free text ("2024", "2024-03", "2024-03-15",
    "2024 Mar 15", "Spring 2024"). We fall back to zeros where parsing fails.
    Later dates sort first when this key is used with ``reverse=True``.
    """
    import re

    if not pubdate:
        return (0, 0, 0)
    text = pubdate.strip()
    year_match = re.search(r"\b(19|20)\d{2}\b", text)
    year = int(year_match.group(0)) if year_match else 0
    month_match = re.search(r"\b(0?[1-9]|1[0-2])\b", text[year_match.end():] if year_match else "")
    month = int(month_match.group(0)) if month_match else 0
    day_match = re.search(r"\b([0-2]?\d|3[01])\b", text[year_match.end():] if year_match else "")
    day = int(day_match.group(0)) if day_match else 0
    if not (1 <= month <= 12):
        month = 0
    if not (1 <= day <= 31):
        day = 0
    return (year, month, day)


def _build_score_distribution(entries: list[dict[str, Any]]) -> dict[str, int]:
    buckets: dict[str, int] = {}
    for entry in entries:
        score = entry.get("score")
        if score is None:
            key = "unscored"
        else:
            key = str(int(round(score)))
        buckets[key] = buckets.get(key, 0) + 1

    def sort_key(item: tuple[str, int]) -> tuple[int, int]:
        bucket, _ = item
        if bucket == "unscored":
            return (0, -1)
        try:
            return (1, int(bucket))
        except ValueError:
            return (0, -1)

    return dict(sorted(buckets.items(), key=sort_key, reverse=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--shortlist",
        required=True,
        help="Path to shortlist.json (relevance-scoring output).",
    )
    parser.add_argument(
        "--download-log",
        required=True,
        help="Path to pdfs/download_log.json produced by Step 4.",
    )
    parser.add_argument(
        "--pubmed-results",
        help="Optional pubmed_results.json for publication-date tie-breaking.",
    )
    parser.add_argument(
        "--score-field",
        help=(
            "Field name in shortlist entries holding the relevance score. "
            f"Auto-detect from {SCORE_FIELD_CANDIDATES} when omitted."
        ),
    )
    parser.add_argument(
        "--top-k",
        type=int,
        help="If provided, truncate the ranked output to the top K entries.",
    )
    parser.add_argument(
        "--suggested-budget",
        type=int,
        default=10,
        help="Default extraction budget to show in the human-readable summary.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the JSON output.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    shortlist = _coerce_shortlist(_load_json(Path(args.shortlist)))
    download_results = _coerce_download_results(_load_json(Path(args.download_log)))

    pubdate_by_doi: dict[str, str] = {}
    if args.pubmed_results:
        for article in _coerce_pubmed(_load_json(Path(args.pubmed_results))):
            doi_key = _normalize_doi(article.get("doi"))
            if doi_key and article.get("pubdate"):
                pubdate_by_doi[doi_key] = str(article["pubdate"])

    downloaded_by_doi: dict[str, dict[str, Any]] = {}
    for entry in download_results:
        status = entry.get("status")
        if status not in DOWNLOADED_STATUSES:
            continue
        doi_key = _normalize_doi(entry.get("doi"))
        if not doi_key:
            continue
        downloaded_by_doi[doi_key] = entry

    ranked: list[dict[str, Any]] = []
    unmatched_shortlist = 0
    for entry in shortlist:
        doi_key = _normalize_doi(entry.get("doi"))
        if not doi_key:
            unmatched_shortlist += 1
            continue
        download_entry = downloaded_by_doi.get(doi_key)
        if not download_entry:
            continue
        score = _pick_score(entry, args.score_field)
        pubdate = entry.get("pubdate") or pubdate_by_doi.get(doi_key, "")
        ranked.append({
            "doi": entry.get("doi") or download_entry.get("doi"),
            "pmid": entry.get("pmid") or download_entry.get("pmid") or "",
            "title": entry.get("title") or download_entry.get("title") or "",
            "score": score,
            "pubdate": pubdate,
            "pdf_path": download_entry.get("pdf_path") or "",
            "download_status": download_entry.get("status") or "",
        })

    ranked.sort(
        key=lambda item: (
            item["score"] if item["score"] is not None else float("-inf"),
            _pubdate_sort_key(item["pubdate"]),
        ),
        reverse=True,
    )

    full_pool_distribution = _build_score_distribution(ranked)

    total_downloaded = len(downloaded_by_doi)
    truncated = False
    if args.top_k is not None and args.top_k >= 0 and args.top_k < len(ranked):
        ranked = ranked[: args.top_k]
        truncated = True

    summary = {
        "shortlist_size": len(shortlist),
        "shortlist_unmatched_no_doi": unmatched_shortlist,
        "downloaded_pdfs": total_downloaded,
        "ranked_returned": len(ranked),
        "truncated": truncated,
        "suggested_budget": min(max(args.suggested_budget, 0), len(ranked)),
        "score_distribution_before_truncation": full_pool_distribution,
    }

    print("=" * 60, file=sys.stderr)
    print("Step 4 → Step 5a bridge", file=sys.stderr)
    print("-" * 60, file=sys.stderr)
    print(f"Shortlisted (relevance-scoring):  {summary['shortlist_size']}", file=sys.stderr)
    print(f"Successfully downloaded: {summary['downloaded_pdfs']}", file=sys.stderr)
    print(f"Ranked candidates:       {summary['ranked_returned']}", file=sys.stderr)
    if truncated:
        print(f"  (truncated to top-{args.top_k} on request)", file=sys.stderr)
    print("Score distribution of downloaded & ranked pool:", file=sys.stderr)
    for bucket, count in full_pool_distribution.items():
        label = f"score {bucket}" if bucket != "unscored" else "unscored"
        print(f"  {label:>12}: {count}", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(
        "Next step: confirm an extraction budget with the user before Step 5a. "
        f"Suggested default is top {summary['suggested_budget']} by score; adjust to taste.",
        file=sys.stderr,
    )

    output = {"summary": summary, "ranked": ranked}
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
