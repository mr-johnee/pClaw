# Structure-Extraction Prompt: Novel Warhead Extraction from Acquired PDF

## Purpose

Read an acquired PDF for a single article and emit a
strict JSON record of novel reactive fragments that could form a stable
covalent bond with the target residue or side-chain functionality under
intended probe-use conditions. The
output feeds
`smiles_to_image.py` for RDKit validation/rendering and the report-composition
prompt for the final academic report. The output must conform to the JSON Schema in
`references/candidate.schema.json`; use native structured-output / JSON Schema
mode when the host model API supports it. Nothing else reads these fields —
stick to that schema so downstream steps remain deterministic.

## Required inputs (provided by the caller)

- `target_residue` — e.g. `Cysteine`, `Lysine`, `Serine`. Used throughout.
- `excluded_classes` — the list of warhead class names drawn from
  `KNOWN_WARHEADS.json` for the `target_residue`. Treat this list as the
  known warhead landscape; candidates matching any class in it must be
  dropped before they enter the output JSON.
- `paper_metadata` — `{doi, pmid, title, journal, year, authors}` from the
  shortlist entry.
- `source_path` — path to the local PDF used.

## Source requirements

Use only a locally acquired PDF. If no PDF was acquired, do not attempt this
prompt for that paper.

## Metadata copy rule

`source_doi`, `source_pmid`, `source_title`, `source_journal`, `source_year`,
and `source_authors` must be copied verbatim from the `paper_metadata` block
the caller passed in. Do not paraphrase, abbreviate, or drop any of these
fields. `source_authors` must be the full author list as it appears in
PubMed (last-name + initials per author, in original order); never emit a
shortened "et al.", a placeholder like `"Authors of ref. N"`, or an empty
array. These fields are downstream-required for ACS-style references and the
report-composition prompt is forbidden from inventing them.

## Batch / Parallel Use

This prompt may be run as a batch of independent one-PDF jobs when the host
environment supports parallel execution or batch inference. Keep one logical
job per PDF and validate each job's output against
`references/candidate.schema.json` before concatenating candidate arrays into
`candidates.json`.

Do not combine many PDFs into one extraction prompt unless the host model has
explicit multi-document support and enough context to preserve per-paper
locators. Single-PDF jobs are slower to launch but much easier to audit,
retry, and manually confirm.

## Scope of extraction

Focus on the **reactive fragment** (warhead / covalent handle) — the minimal
motif that forms the target covalent linkage. Also capture the full parent
molecule for context. Skip starting materials, auxiliary reagents, trapping
agents, and linker/ligand portions unless they are themselves the reactive
handle.

Only extract candidates whose structure is explicitly drawn in a figure,
scheme, or table, or is otherwise specified with enough fidelity in the source
to support a confident structure assignment. Text-only mentions without a
drawn structure normally do not qualify.

Record the exact source locator for the drawn structure in `structure_source`.
If the caller has created a screenshot crop for that figure/scheme/table, put
its relative path in `structure_source.screenshot_path`; otherwise use an empty
string. Screenshot availability is an audit aid, not a substitute for the page
and figure/scheme/table locator.

## Exclusion rules (must be applied before emitting output)

Drop a candidate if any of the following is true:

1. Its warhead class clearly matches an entry in `excluded_classes`.
2. The paper studies it only for analytical detection, biosensing,
   materials characterization, or pure computational/theoretical analysis
   with no chemical reactivity evidence.
3. It requires conditions or activation modes that cannot plausibly be adapted
   to the intended probe-use setting. Photochemical, redox, enzymatic, or
   metal-mediated chemistry is not automatically disqualifying; drop it only
   when the required activation, catalyst, temperature, solvent, or additives
   are incompatible with the requested use context and no transferable
   reactive-handle insight remains.
4. Its only reaction mode is metal coordination (coordinate covalent bonds
   are out of scope) or polymerization/cross-linking.

### Structural similarity is not a disqualifier

If a candidate shares a backbone with a class in `excluded_classes` but the
**reaction mechanism, electronic activation, or selectivity profile** is
materially different (e.g. a polarized enone activated without a sulfonyl
group when the excluded class is vinyl sulfone), keep the candidate and
record the distinguishing feature in `novelty_reasoning`. Let the final
reader decide.

## Reactivity scoring

Score on 1–10. Thresholds:

| Score | Meaning |
|-------|---------|
| 9–10  | Direct evidence under the requested or closely related probe-use conditions, with practical minutes-to-hours kinetics and compatible activation requirements |
| 7–8   | Strong mechanistic case: either near-use-condition evidence or compelling indirect evidence plus established mechanistic precedent |
| 5–6   | Mechanism plausible but needs significant optimization; typically conditions or activation modes need adaptation |
| 1–4   | Weak / no reactivity evidence for the target functionality |

Only candidates with `reactivity_score ≥ 7` should appear in the output.

## Confidence fields

Two independent 1–10 scores are required per candidate. Do not conflate them.

- `smiles_confidence` — how faithfully the emitted `warhead_smiles` captures
  the drawn structure. Lowered by ambiguous stereochemistry, unclear
  tautomers, large or fused ring systems that were hard to read from the
  figure, or partial-structure drawings.
- `reactivity_confidence` — how certain you are that the reactivity claims
  hold under the requested or plausible probe-use conditions. Lowered by weak
  mechanistic precedent, conditions that require major adaptation, or
  selectivity claims supported by a single data point.

Set `manual_review_status` to `model_extracted` for every newly emitted
candidate. Only a human reviewer may later change it to `human_confirmed` or
`rejected_after_review`; use `needs_manual_review` when the drawing, SMILES,
or reactivity claim is ambiguous enough that it should not be used in a
publication-facing conclusion.

## Evidence contract

Every quantitative or specific claim about reactivity, mechanism,
selectivity, stability, or kinetics must cite a concrete anchor in the
paper. Claims without an anchor must be removed.

Schema per evidence item:

```json
{
  "claim": "short statement of what was demonstrated",
  "quote": "1-2 sentence direct quote or tight paraphrase",
  "location": {
    "type": "figure | scheme | table | text",
    "id": "e.g. Figure 4 / Scheme 2 / Table 1",
    "page": 5
  }
}
```

If a claim cannot be backed by a locator, drop the claim rather than
invent one.

## Output schema

Emit a JSON array matching `references/candidate.schema.json`. Each element
describes one novel candidate:

The example below is illustrative only. Do not treat the residue, mechanism,
conditions, or comparison classes shown here as defaults for other targets.

```json
{
  "id": 1,
  "source_doi": "10.xxxx/yyyy",
  "source_pmid": "12345678",
  "source_title": "...",
  "source_journal": "J. Am. Chem. Soc.",
  "source_year": 2024,
  "source_authors": ["Smith J", "Lee K", "Patel R"],

  "warhead_smiles": "C=C(C#N)C(=O)N",
  "parent_smiles": "C=C(C#N)C(=O)NCC1=CC=CC=C1",
  "warhead_name": "α-cyanoenone amide",
  "mechanistic_family": "polarized α-cyanoenone",
  "mechanistic_family_normalized": "polarized_alpha_cyanoenone",
  "target_residue": "Cysteine",

  "reaction_mechanism": "1,4-Michael addition at Cys-Sγ; α-CN group polarises the enone independent of a sulfonyl activator.",
  "physiological_conditions": "pH 7.4, 37°C, aqueous buffer with 1 mM GSH",
  "kinetics": "k2 ≈ 12 M^-1 s^-1 with GSH",
  "selectivity_notes": "20× faster than the chloroacetamide analog in the same study; no detectable reaction with Lys/His.",

  "evidence": [
    {"claim": "...", "quote": "...", "location": {"type": "table", "id": "Table 2", "page": 5}}
  ],
  "structure_source": {
    "type": "scheme",
    "id": "Scheme 2",
    "page": 4,
    "screenshot_path": ""
  },

  "novelty_reasoning": "Nearest class in excluded_classes is vinyl sulfone; this candidate replaces SO2R with CN, removing the sulfonyl activator and shifting electronic profile.",

  "structure_role": "core_candidate",
  "manual_review_status": "model_extracted",
  "reactivity_score": 9,
  "reactivity_confidence": 9,
  "smiles_confidence": 8
}
```

Allowed `structure_role` values: `core_candidate`, `supporting_structure`.
Do not emit `background_reagent` entries — if that is the role, omit the
candidate.

## What NOT to include in the output

- Do not insert prose commentary, markdown, or headings outside the JSON.
- Do not compute or emit `canonical_smiles`, `image_path`, or
  `validation_status`. Those are filled in by `smiles_to_image.py`.
- Do not attempt cross-paper deduplication. Report every qualifying
  candidate per paper independently; the report-composition prompt merges by
  canonical SMILES.
- Do not emit candidates with `reactivity_score < 7`.
- Do not mark candidates as `human_confirmed`; that status is reserved for
  manual post-extraction review.

## If nothing qualifies

Emit an empty JSON array `[]`. Do not pad with low-confidence guesses.
