#!/usr/bin/env python3
"""Validate candidate SMILES and render their structures as PNG images.

Input is a ``candidates.json`` file produced by the structure-extraction step,
a JSON array of objects each with at least a ``warhead_smiles`` field.

For each candidate the script:

1. Parses ``warhead_smiles`` with RDKit. Failures are recorded as
   ``validation_status = "invalid_smiles"`` and no image is rendered.
2. Computes a canonical SMILES and stores it as ``canonical_smiles``.
3. Renders a PNG to ``<images-dir>/candidate_<id>.png`` and stores the path
   in ``image_path``.

The enriched list is written back to ``--output`` (defaulting to
``candidates.enriched.json``). Deduplication across papers is NOT performed
here — downstream report composition handles that by comparing canonical
SMILES across entries.

Example
-------

    python3 smiles_to_image.py \\
        --input candidates.json \\
        --output candidates.enriched.json \\
        --images-dir images
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


def _load_rdkit():
    try:
        from rdkit import Chem  # noqa: WPS433
        from rdkit.Chem import Draw  # noqa: WPS433
    except ImportError as exc:
        raise SystemExit(
            "RDKit is required for smiles_to_image.py. "
            "Install it with `pip install rdkit` and retry."
        ) from exc
    return Chem, Draw


def _load_candidates(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("candidates", "items", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    raise ValueError(
        f"Unsupported candidate file shape in {path}; "
        "expected a JSON array or an object with a 'candidates' array."
    )


def _assign_id(candidate: dict[str, Any], index: int) -> int:
    existing = candidate.get("id")
    if isinstance(existing, int) and existing > 0:
        return existing
    candidate["id"] = index
    return index


def _normalize_class_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("α", "alpha").replace("β", "beta").replace("γ", "gamma")
    text = text.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        required=True,
        help="Path to candidates JSON from the structure-extraction step.",
    )
    parser.add_argument(
        "--output",
        default="candidates.enriched.json",
        help="Where to write the enriched JSON.",
    )
    parser.add_argument(
        "--images-dir",
        default="images",
        help="Directory for rendered structure PNGs.",
    )
    parser.add_argument(
        "--image-size",
        type=int,
        default=400,
        help="PNG side length in pixels (square).",
    )
    parser.add_argument(
        "--smiles-field",
        default="warhead_smiles",
        help="Candidate field holding the SMILES to validate and render.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print the resulting JSON.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    Chem, Draw = _load_rdkit()

    input_path = Path(args.input).resolve()
    output_path = Path(args.output).resolve()
    images_dir = Path(args.images_dir).resolve()
    images_dir.mkdir(parents=True, exist_ok=True)

    candidates = _load_candidates(input_path)
    total = len(candidates)
    valid = 0
    invalid = 0
    seen_canonical: dict[str, int] = {}

    for index, candidate in enumerate(candidates, start=1):
        candidate_id = _assign_id(candidate, index)
        candidate.setdefault("manual_review_status", "model_extracted")
        if not candidate.get("mechanistic_family_normalized"):
            candidate["mechanistic_family_normalized"] = _normalize_class_label(
                candidate.get("mechanistic_family") or candidate.get("warhead_name")
            )
        smiles = (candidate.get(args.smiles_field) or "").strip()
        if not smiles:
            candidate["validation_status"] = "missing_smiles"
            invalid += 1
            continue

        mol = Chem.MolFromSmiles(smiles)
        if mol is None:
            candidate["validation_status"] = "invalid_smiles"
            invalid += 1
            continue

        canonical = Chem.MolToSmiles(mol)
        image_path = images_dir / f"candidate_{candidate_id:03d}.png"
        Draw.MolToFile(mol, str(image_path), size=(args.image_size, args.image_size))

        duplicate_of = seen_canonical.get(canonical)
        if duplicate_of is None:
            seen_canonical[canonical] = candidate_id
            candidate["duplicate_of_id"] = None
        else:
            candidate["duplicate_of_id"] = duplicate_of
        candidate["canonical_smiles"] = canonical
        candidate["image_path"] = str(image_path)
        candidate["validation_status"] = "ok"
        valid += 1

    summary = {
        "input": str(input_path),
        "output": str(output_path),
        "images_dir": str(images_dir),
        "totals": {"total": total, "valid": valid, "invalid": invalid},
    }

    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(candidates, handle, ensure_ascii=False, indent=2)

    json.dump(
        summary,
        sys.stdout,
        ensure_ascii=False,
        indent=2 if args.pretty else None,
    )
    sys.stdout.write("\n")
    return 0 if invalid == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
