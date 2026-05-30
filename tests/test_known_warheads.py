"""Schema checks for the bundled known-warhead exclusion list."""

from __future__ import annotations

import json
from pathlib import Path


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "known_warheads.json"

EXPECTED_RESIDUES = {
    "Cysteine",
    "Lysine",
    "Serine",
    "Histidine",
    "Tyrosine",
    "Threonine",
    "Aspartic Acid",
    "Glutamic Acid",
    "Methionine",
}


def test_file_exists() -> None:
    assert DATA_PATH.is_file(), f"Missing {DATA_PATH}"


def test_covers_expected_residues() -> None:
    with DATA_PATH.open() as handle:
        data = json.load(handle)
    residue_keys = set(data) - {"_metadata"}
    assert EXPECTED_RESIDUES.issubset(residue_keys), (
        f"Missing residues: {EXPECTED_RESIDUES - residue_keys}"
    )


def test_entries_are_non_empty_string_lists() -> None:
    with DATA_PATH.open() as handle:
        data = json.load(handle)
    for residue, classes in data.items():
        if residue == "_metadata":
            continue
        assert isinstance(classes, list) and classes, (
            f"{residue} must have a non-empty list of warhead classes"
        )
        for cls in classes:
            assert isinstance(cls, str) and cls.strip(), (
                f"{residue} contains a non-string or empty class entry: {cls!r}"
            )


def test_metadata_has_version() -> None:
    with DATA_PATH.open() as handle:
        data = json.load(handle)
    metadata = data.get("_metadata", {})
    assert metadata.get("version"), "Metadata must carry a version string."


def test_metadata_has_source_provenance() -> None:
    with DATA_PATH.open() as handle:
        data = json.load(handle)
    metadata = data.get("_metadata", {})
    assert metadata.get("source_name")
    assert metadata.get("source_url")
