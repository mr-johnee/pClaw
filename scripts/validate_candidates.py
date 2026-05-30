#!/usr/bin/env python3
"""Validate structure-extraction / Step 5 candidate JSON without relying on model support.

This script first validates the candidate list against the bundled JSON Schema,
then checks workflow rules that make model-extracted candidates suitable for
human review before publication.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parent.parent / "references" / "candidate.schema.json"

REQUIRED_STRING_FIELDS = (
    "source_doi",
    "source_title",
    "warhead_smiles",
    "warhead_name",
    "mechanistic_family",
    "mechanistic_family_normalized",
    "target_residue",
    "reaction_mechanism",
    "novelty_reasoning",
    "structure_role",
    "manual_review_status",
)

REQUIRED_SCORE_FIELDS = (
    "reactivity_score",
    "reactivity_confidence",
    "smiles_confidence",
)

MANUAL_REVIEW_STATUSES = frozenset(
    {
        "model_extracted",
        "needs_manual_review",
        "human_confirmed",
        "rejected_after_review",
    }
)

STRUCTURE_ROLES = frozenset({"core_candidate", "supporting_structure"})
LOCATION_TYPES = frozenset({"figure", "scheme", "table", "text"})


def normalize_class_label(value: Any) -> str:
    """Return a conservative comparable label for warhead-class names."""

    text = str(value or "").strip().lower()
    text = text.replace("α", "alpha").replace("β", "beta").replace("γ", "gamma")
    text = text.replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _load_candidates(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if isinstance(data, list):
        return [entry for entry in data if isinstance(entry, dict)]
    if isinstance(data, dict):
        for key in ("candidates", "items", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return [entry for entry in value if isinstance(entry, dict)]
    raise ValueError(
        f"Unsupported candidate file shape in {path}; expected a JSON array "
        "or an object with a 'candidates' array."
    )


def _validate_json_schema(
    data: Any, schema_path: Path | None
) -> list[str]:
    if schema_path is None:
        return []
    try:
        import jsonschema
    except ImportError as exc:
        raise SystemExit(
            "jsonschema is required for schema validation. Install dependencies "
            "with `python3 -m pip install -r requirements.txt`."
        ) from exc

    with schema_path.open("r", encoding="utf-8") as handle:
        schema = json.load(handle)

    validator_cls = jsonschema.validators.validator_for(schema)
    validator_cls.check_schema(schema)
    validator = validator_cls(schema)
    errors = sorted(validator.iter_errors(data), key=lambda error: list(error.path))

    messages: list[str] = []
    for error in errors:
        path = "$"
        if error.path:
            path += "".join(
                f"[{part}]" if isinstance(part, int) else f".{part}"
                for part in error.path
            )
        messages.append(f"{path}: {error.message}")
    return messages


def _load_known_classes(path: Path | None, target_residue: str | None) -> set[str]:
    if not path:
        return set()
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    classes: list[Any] = []
    if target_residue and isinstance(data, dict):
        classes = data.get(target_residue) or []
    if not classes and isinstance(data, dict):
        for key, value in data.items():
            if key == "_metadata" or not isinstance(value, list):
                continue
            classes.extend(value)
    return {normalize_class_label(item) for item in classes if str(item).strip()}


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _validate_score(
    entry: dict[str, Any], field: str, index: int, errors: list[str]
) -> None:
    value = entry.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        errors.append(f"candidate {index}: {field} must be a number")
        return
    if not 1 <= float(value) <= 10:
        errors.append(f"candidate {index}: {field} must be between 1 and 10")


def _validate_evidence(entry: dict[str, Any], index: int, errors: list[str]) -> None:
    evidence = entry.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        errors.append(f"candidate {index}: evidence must be a non-empty list")
        return
    for ev_index, item in enumerate(evidence, start=1):
        if not isinstance(item, dict):
            errors.append(f"candidate {index} evidence {ev_index}: must be an object")
            continue
        for field in ("claim", "quote"):
            if not _is_nonempty_string(item.get(field)):
                errors.append(
                    f"candidate {index} evidence {ev_index}: {field} is required"
                )
        location = item.get("location")
        if not isinstance(location, dict):
            errors.append(
                f"candidate {index} evidence {ev_index}: location must be an object"
            )
            continue
        if location.get("type") not in LOCATION_TYPES:
            errors.append(
                f"candidate {index} evidence {ev_index}: location.type must be "
                f"one of {sorted(LOCATION_TYPES)}"
            )
        if not _is_nonempty_string(location.get("id")):
            errors.append(f"candidate {index} evidence {ev_index}: location.id is required")
        page = location.get("page")
        if not isinstance(page, int) or page < 1:
            errors.append(
                f"candidate {index} evidence {ev_index}: location.page must be a positive integer"
            )


def _validate_structure_source(
    entry: dict[str, Any], index: int, errors: list[str]
) -> None:
    source = entry.get("structure_source")
    if not isinstance(source, dict):
        errors.append(f"candidate {index}: structure_source must be an object")
        return
    if source.get("type") not in LOCATION_TYPES - {"text"}:
        errors.append(
            f"candidate {index}: structure_source.type must be figure, scheme, or table"
        )
    if not _is_nonempty_string(source.get("id")):
        errors.append(f"candidate {index}: structure_source.id is required")
    page = source.get("page")
    if not isinstance(page, int) or page < 1:
        errors.append(f"candidate {index}: structure_source.page must be a positive integer")


def validate_candidates(
    candidates: list[dict[str, Any]],
    known_classes: set[str],
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    seen_smiles: dict[str, int] = {}

    for index, entry in enumerate(candidates, start=1):
        for field in REQUIRED_STRING_FIELDS:
            if not _is_nonempty_string(entry.get(field)):
                errors.append(f"candidate {index}: {field} is required")

        for field in REQUIRED_SCORE_FIELDS:
            _validate_score(entry, field, index, errors)

        if entry.get("structure_role") not in STRUCTURE_ROLES:
            errors.append(
                f"candidate {index}: structure_role must be one of {sorted(STRUCTURE_ROLES)}"
            )

        if entry.get("manual_review_status") not in MANUAL_REVIEW_STATUSES:
            errors.append(
                f"candidate {index}: manual_review_status must be one of "
                f"{sorted(MANUAL_REVIEW_STATUSES)}"
            )

        if entry.get("manual_review_status") != "human_confirmed":
            warnings.append(
                f"candidate {index}: manual_review_status is "
                f"{entry.get('manual_review_status')!r}; do not treat as publication-ready"
            )

        normalized = normalize_class_label(entry.get("mechanistic_family_normalized"))
        if known_classes and normalized in known_classes:
            warnings.append(
                f"candidate {index}: normalized class {normalized!r} matches known-warhead list"
            )

        _validate_evidence(entry, index, errors)
        _validate_structure_source(entry, index, errors)

        smiles_key = str(
            entry.get("canonical_smiles") or entry.get("warhead_smiles") or ""
        ).strip()
        if smiles_key:
            previous = seen_smiles.get(smiles_key)
            if previous is not None:
                warnings.append(
                    f"candidate {index}: duplicate structure key also appears in candidate {previous}"
                )
            else:
                seen_smiles[smiles_key] = index

    return errors, warnings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        required=True,
        help="Path to candidates.json or candidates.enriched.json.",
    )
    parser.add_argument(
        "--known-warheads",
        help="Optional known_warheads.json for normalized class overlap checks.",
    )
    parser.add_argument(
        "--target-residue",
        help="Residue key to use when loading --known-warheads.",
    )
    parser.add_argument(
        "--warnings-as-errors",
        action="store_true",
        help="Return non-zero if warnings are present.",
    )
    parser.add_argument(
        "--schema",
        default=str(DEFAULT_SCHEMA_PATH),
        help=(
            "JSON Schema file used to validate candidate structure. Defaults "
            "to references/candidate.schema.json. Pass an empty string to disable."
        ),
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    input_path = Path(args.input)
    try:
        with input_path.open("r", encoding="utf-8") as handle:
            raw_data = json.load(handle)
    except json.JSONDecodeError as exc:
        output = {
            "input": str(input_path.resolve()),
            "schema": str(Path(args.schema).resolve()) if args.schema else "",
            "candidate_count": 0,
            "error_count": 1,
            "warning_count": 0,
            "errors": [f"invalid JSON: {exc}"],
            "warnings": [],
        }
        json.dump(output, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
        sys.stdout.write("\n")
        return 1
    schema_path = Path(args.schema) if args.schema else None
    schema_errors = _validate_json_schema(raw_data, schema_path)
    candidates = _load_candidates(input_path)
    known_classes = _load_known_classes(
        Path(args.known_warheads) if args.known_warheads else None,
        args.target_residue,
    )
    errors, warnings = validate_candidates(candidates, known_classes)
    errors = schema_errors + errors

    output = {
        "input": str(input_path.resolve()),
        "schema": str(schema_path.resolve()) if schema_path else "",
        "candidate_count": len(candidates),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }
    json.dump(output, sys.stdout, ensure_ascii=False, indent=2 if args.pretty else None)
    sys.stdout.write("\n")

    if errors or (warnings and args.warnings_as_errors):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
