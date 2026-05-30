#!/usr/bin/env python3
"""Orchestrate the deterministic stages of the covalent-probe-discovery pipeline.

This wrapper runs the steps that do not require an LLM: PubMed search (Step 2),
OA PDF acquisition (Step 4), RDKit validation / rendering (Step 5b), and
candidate-contract validation (Step 5b audit). The
LLM-driven steps (keyword generation, relevance scoring, structure extraction,
and report composition) remain the caller's responsibility and follow the
prompts in ``references/``.

Typical invocation from a run directory::

    python3 scripts/run_pipeline.py --keywords keywords.txt

If ``shortlist.json`` is already present (produced by the relevance-scoring
step), Step 4 runs as well. If ``candidates.json`` is already present (produced
by the structure-extraction step), Step 5b runs too.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent


def _run(cmd: list[str]) -> int:
    print(f"\n$ {' '.join(cmd)}", file=sys.stderr)
    return subprocess.call(cmd)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keywords",
        default="keywords.txt",
        help="Path to the keyword file produced by the keyword-generation step.",
    )
    parser.add_argument(
        "--pubmed-output",
        default="pubmed_results.json",
        help="Where to write PubMed search results.",
    )
    parser.add_argument(
        "--shortlist",
        default="shortlist.json",
        help="Shortlist file produced by the relevance-scoring step (Step 4 runs only if present).",
    )
    parser.add_argument(
        "--pdf-dir",
        default="pdfs",
        help="Directory for acquired PDFs.",
    )
    parser.add_argument(
        "--download-workers",
        type=int,
        default=1,
        help="Concurrent workers for Step 4 PDF acquisition.",
    )
    parser.add_argument(
        "--candidates",
        default="candidates.json",
        help="Candidate JSON produced by the structure-extraction step (Step 5b runs only if present).",
    )
    parser.add_argument(
        "--candidates-enriched",
        default="candidates.enriched.json",
        help="Where to write the RDKit-enriched candidate JSON.",
    )
    parser.add_argument(
        "--images-dir",
        default="images",
        help="Directory for rendered structure PNGs.",
    )
    parser.add_argument(
        "--known-warheads",
        help=(
            "Optional known_warheads.json override. Also exported as "
            "COVALENT_PROBE_KNOWN_WARHEADS for downstream manual structure-extraction use."
        ),
    )
    parser.add_argument(
        "--target-residue",
        help="Residue key used for candidate validation against known warheads.",
    )
    parser.add_argument(
        "--retmax",
        type=int,
        default=20,
        help="PubMed results per query.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=50,
        help="Drop PubMed hits whose parseable page count exceeds this value.",
    )
    parser.add_argument(
        "--skip-pubmed",
        action="store_true",
        help="Skip Step 2 even if the keyword file exists.",
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help="Skip Step 4 even if a shortlist is present.",
    )
    parser.add_argument(
        "--skip-render",
        action="store_true",
        help="Skip Step 5b even if a candidates file is present.",
    )
    parser.add_argument(
        "--skip-validate",
        action="store_true",
        help="Skip candidate contract validation after Step 5b rendering.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    keywords_path = Path(args.keywords)
    shortlist_path = Path(args.shortlist)
    candidates_path = Path(args.candidates)
    env = os.environ.copy()
    if args.known_warheads:
        known_path = Path(args.known_warheads).resolve()
        if not known_path.is_file():
            print(f"[run_pipeline] Missing --known-warheads file: {known_path}", file=sys.stderr)
            return 2
        env["COVALENT_PROBE_KNOWN_WARHEADS"] = str(known_path)

    # Step 2 — PubMed search
    if not args.skip_pubmed and keywords_path.is_file():
        cmd = [
            sys.executable,
            str(SCRIPTS_DIR / "pubmed_search.py"),
            "--query-file",
            str(keywords_path),
            "--retmax",
            str(args.retmax),
            "--max-pages",
            str(args.max_pages),
            "--pretty",
        ]
        with Path(args.pubmed_output).open("w", encoding="utf-8") as sink:
            print(f"\n$ {' '.join(cmd)} > {args.pubmed_output}", file=sys.stderr)
            rc = subprocess.call(cmd, stdout=sink, env=env)
        if rc != 0:
            return rc
    elif not args.skip_pubmed:
        print(
            f"[run_pipeline] Skipping Step 2: {keywords_path} not found.",
            file=sys.stderr,
        )

    # Step 4 — OA PDF acquisition
    if not args.skip_download and shortlist_path.is_file():
        rc = _run([
            sys.executable,
            str(SCRIPTS_DIR / "download_pdf.py"),
            "--shortlist",
            str(shortlist_path),
            "--output-dir",
            args.pdf_dir,
            "--workers",
            str(args.download_workers),
            "--pretty",
        ])
        if rc not in (0, 1):
            return rc
    elif not args.skip_download:
        print(
            f"[run_pipeline] Skipping Step 4: {shortlist_path} not found. "
            "Produce it with the relevance-scoring prompt before rerunning.",
            file=sys.stderr,
        )

    # Step 5b — RDKit validation and rendering
    if not args.skip_render and candidates_path.is_file():
        rc = _run([
            sys.executable,
            str(SCRIPTS_DIR / "smiles_to_image.py"),
            "--input",
            str(candidates_path),
            "--output",
            args.candidates_enriched,
            "--images-dir",
            args.images_dir,
            "--pretty",
        ])
        if rc not in (0, 1):
            return rc

        if not args.skip_validate:
            validate_cmd = [
                sys.executable,
                str(SCRIPTS_DIR / "validate_candidates.py"),
                "--input",
                args.candidates_enriched,
                "--schema",
                str(SCRIPTS_DIR.parent / "references" / "candidate.schema.json"),
                "--pretty",
            ]
            known_for_validation = (
                args.known_warheads
                or env.get("COVALENT_PROBE_KNOWN_WARHEADS")
            )
            if known_for_validation:
                validate_cmd.extend(["--known-warheads", known_for_validation])
            if args.target_residue:
                validate_cmd.extend(["--target-residue", args.target_residue])
            validate_rc = _run(validate_cmd)
            if validate_rc != 0:
                return validate_rc
    elif not args.skip_render:
        print(
            f"[run_pipeline] Skipping Step 5b: {candidates_path} not found. "
            "Produce it with the structure-extraction prompt before rerunning.",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
