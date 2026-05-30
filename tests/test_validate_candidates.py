"""Tests for scripts/validate_candidates.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "scripts" / "validate_candidates.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("validate_candidates", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _candidate() -> dict:
    return {
        "source_doi": "10.1/example",
        "source_title": "Example paper",
        "warhead_smiles": "C=CC(=O)N",
        "warhead_name": "acrylamide",
        "mechanistic_family": "polarized alpha cyanoenone",
        "mechanistic_family_normalized": "polarized_alpha_cyanoenone",
        "target_residue": "Cysteine",
        "reaction_mechanism": "Michael addition.",
        "novelty_reasoning": "Different activation pattern.",
        "structure_role": "core_candidate",
        "manual_review_status": "human_confirmed",
        "reactivity_score": 8,
        "reactivity_confidence": 7,
        "smiles_confidence": 8,
        "evidence": [
            {
                "claim": "Observed reaction in buffer.",
                "quote": "Reaction was observed.",
                "location": {"type": "table", "id": "Table 1", "page": 3},
            }
        ],
        "structure_source": {
            "type": "scheme",
            "id": "Scheme 1",
            "page": 2,
            "screenshot_path": "",
        },
    }


def test_valid_candidate_passes() -> None:
    mod = _load_module()
    errors, warnings = mod.validate_candidates([_candidate()], set())
    assert errors == []
    assert warnings == []


def test_model_extracted_warns_not_errors() -> None:
    mod = _load_module()
    candidate = _candidate()
    candidate["manual_review_status"] = "model_extracted"
    errors, warnings = mod.validate_candidates([candidate], set())
    assert errors == []
    assert any("publication-ready" in warning for warning in warnings)


def test_known_class_overlap_warns() -> None:
    mod = _load_module()
    errors, warnings = mod.validate_candidates(
        [_candidate()],
        {"polarized_alpha_cyanoenone"},
    )
    assert errors == []
    assert any("known-warhead" in warning for warning in warnings)


def test_missing_structure_source_is_error() -> None:
    mod = _load_module()
    candidate = _candidate()
    candidate.pop("structure_source")
    errors, _ = mod.validate_candidates([candidate], set())
    assert any("structure_source" in error for error in errors)
