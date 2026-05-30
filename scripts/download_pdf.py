#!/usr/bin/env python3
"""Download open-access PDFs for a batch of shortlisted articles.

Input options
-------------

* ``--doi`` (repeatable) — download a single paper by DOI.
* ``--shortlist <path>`` — JSON file produced by relevance scoring. The file
  may be either a list of article objects or a dict containing an
  ``articles`` list. Each article must expose ``doi``; ``title`` and ``pmid``
  are used when available.

Output
------

One subdirectory per paper under ``--output-dir`` (default ``pdfs/``)
containing ``paper.pdf`` when a compliant OA route succeeds. The downloader
tries Europe PMC direct PDF, PMC's official OA service/package route, and then
other Unpaywall-reported OA PDF locations. A ``download_log.json`` manifest is
written to the same directory summarizing successes and failures.

Example
-------

    python3 download_pdf.py --shortlist shortlisted.json --output-dir pdfs --pretty
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
from pathlib import Path
from typing import Any


SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from chemdeep_pdf import download_pdf_for_paper  # noqa: E402


def _load_shortlist(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        entries = data
    elif isinstance(data, dict):
        entries = data.get("articles") or data.get("shortlist") or []
    else:
        raise ValueError(f"Unsupported shortlist shape in {path}")
    if not isinstance(entries, list):
        raise ValueError(f"Shortlist in {path} must be a JSON array of articles")
    return entries


def _collect_jobs(args: argparse.Namespace) -> list[dict[str, str]]:
    jobs: list[dict[str, str]] = []
    for doi in args.doi or []:
        doi_clean = doi.strip()
        if doi_clean:
            jobs.append({"doi": doi_clean, "title": "", "pmid": ""})
    if args.shortlist:
        for entry in _load_shortlist(Path(args.shortlist)):
            doi = (entry.get("doi") or "").strip()
            if not doi:
                continue
            jobs.append(
                {
                    "doi": doi,
                    "title": entry.get("title") or "",
                    "pmid": entry.get("pmid") or "",
                }
            )
    return _dedupe_by_doi(jobs)


def _dedupe_by_doi(jobs: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for job in jobs:
        doi_key = job["doi"].lower()
        if doi_key in seen:
            continue
        seen.add(doi_key)
        unique.append(job)
    return unique


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--doi", action="append", help="DOI to download. Repeatable."
    )
    parser.add_argument(
        "--shortlist",
        help="JSON file holding shortlisted articles with DOI / title / pmid fields.",
    )
    parser.add_argument(
        "--output-dir",
        default="pdfs",
        help="Directory that will hold one subfolder per paper.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=1.5,
        help=(
            "Pause between download submissions to avoid hammering upstream OA "
            "providers. With --workers > 1 this still staggers task submission."
        ),
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help=(
            "Number of concurrent download workers. Keep this modest for public "
            "OA services; default is sequential."
        ),
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=True,
        help="Skip papers whose paper.pdf already exists (default: on).",
    )
    parser.add_argument(
        "--redownload",
        action="store_true",
        help="Redownload papers even if paper.pdf already exists.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )
    return parser


def _existing_pdf(output_dir: Path, doi: str) -> Path | None:
    import re

    article_id = re.sub(r'[\\/*?:"<>|]', "_", doi.lower())
    candidate = output_dir / article_id / "paper.pdf"
    return candidate if candidate.exists() else None


def _process_job(
    index: int,
    total: int,
    job: dict[str, str],
    output_dir: Path,
    skip_existing: bool,
) -> tuple[int, dict[str, Any], str]:
    doi = job["doi"]
    if skip_existing:
        existing = _existing_pdf(output_dir, doi)
        if existing is not None:
            return (
                index,
                {
                    "doi": doi,
                    "title": job["title"],
                    "pmid": job["pmid"],
                    "status": "skipped_existing",
                    "pdf_path": str(existing),
                },
                "skipped_existing",
            )

    print(f"[{index}/{total}] Downloading {doi}", file=sys.stderr)
    outcome = download_pdf_for_paper(
        doi=doi,
        title=job["title"],
        output_dir=output_dir,
    )
    status = "ok" if outcome.get("success") else "failed"
    record = {
        "doi": doi,
        "title": job["title"],
        "pmid": job["pmid"],
        "status": status,
        **{k: v for k, v in outcome.items() if k not in {"doi", "title"}},
    }
    return index, record, status


def main() -> int:
    args = build_parser().parse_args()
    jobs = _collect_jobs(args)
    if not jobs:
        print("No DOIs to process. Use --doi or --shortlist.", file=sys.stderr)
        return 2

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    skip_existing = args.skip_existing and not args.redownload
    workers = max(args.workers, 1)

    results: list[dict[str, Any]] = []
    successes = 0
    failures = 0
    skipped = 0

    indexed_results: list[tuple[int, dict[str, Any], str]] = []
    if workers == 1:
        for index, job in enumerate(jobs, start=1):
            indexed_results.append(
                _process_job(index, len(jobs), job, output_dir, skip_existing)
            )
            if index < len(jobs):
                time.sleep(max(args.delay_seconds, 0))
    else:
        print(
            f"[download_pdf] Using {workers} workers with "
            f"{max(args.delay_seconds, 0):.2f}s submission delay.",
            file=sys.stderr,
        )
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            futures: list[concurrent.futures.Future[tuple[int, dict[str, Any], str]]] = []
            for index, job in enumerate(jobs, start=1):
                futures.append(
                    executor.submit(
                        _process_job,
                        index,
                        len(jobs),
                        job,
                        output_dir,
                        skip_existing,
                    )
                )
                if index < len(jobs):
                    time.sleep(max(args.delay_seconds, 0))
            for future in concurrent.futures.as_completed(futures):
                indexed_results.append(future.result())

    for _, record, status in sorted(indexed_results, key=lambda item: item[0]):
        results.append(record)
        if status == "ok":
            successes += 1
        elif status == "skipped_existing":
            skipped += 1
        else:
            failures += 1

    manifest = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "output_dir": str(output_dir),
        "workers": workers,
        "totals": {
            "requested": len(jobs),
            "succeeded": successes,
            "failed": failures,
            "skipped_existing": skipped,
        },
        "results": results,
    }

    log_path = output_dir / "download_log.json"
    with log_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)

    json.dump(
        manifest,
        sys.stdout,
        ensure_ascii=False,
        indent=2 if args.pretty else None,
        default=str,
    )
    sys.stdout.write("\n")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
