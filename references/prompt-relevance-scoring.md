# Relevance-Scoring Prompt

Evaluate articles based on title, abstract, and journal name to determine the likelihood that described chemical methodologies or structures could form stable covalent linkages with the target functionality under mild, synthetically practical or probe-relevant conditions.

If the abstract does not state this directly, predict whether the full article is still likely to contain target-reactive structures, reagents, scaffolds, precursor classes, or mechanism-level insights meaningfully relevant to that goal.

## Target Analysis

For the given target functional group, identify:
- Key reactive sites or reactive-handle family capable of covalent bond formation
- Likely reactivity properties under intended use conditions (pKa, reactive-center polarity when applicable, redox behavior, strain, leaving-group behavior, activation requirements)
- Typical reaction classes and structural motifs expected to react
- Expected reaction behavior under probe-relevant conditions

### Target-Relevant Mild / Practical Conditions

- Favor chemistry demonstrated under mild, synthetically practical conditions
- Strong evidence includes chemoselective or target-compatible reactivity under reasonable conditions
- Highly aqueous or biological-use-compatible settings are strong positive evidence but not mandatory
- Synthetic or non-aqueous studies are still relevant if they clearly introduce transferable structures, reagents, precursor classes, or mechanisms

## Hard Score Caps

If any of the following applies, cap the score at ≤ 4 regardless of other signals:

- **Analytical-oriented studies:** Detection, biosensing, characterization.
- **Pure computational/theoretical studies:** No experimental methodology.
- **Materials science:** Polymer, nanomaterial, or macromolecular systems where the reactive chemistry is incidental to the material design.
- **Biological function studies:** Protein function or cell biology without a transferable chemical-modification methodology.
- **Application-first studies:** The primary contribution is a specific biological, device, or delivery application rather than reactive chemistry or structural design.

## Novelty Attribution Gate

Before assigning a score ≥ 7, confirm the paper's primary novelty lies in the
**reactive chemistry or structural design** itself. Qualifying contributions
include:

- New reactive motifs, new activation modes, or new mechanistic classes for
  covalent bond formation.
- Synthetic methodology papers that reveal transferable reactive structures
  or activation strategies — including papers that do not themselves target
  the residue of interest — when the chemistry they introduce exposes
  structural or mechanistic inspiration reusable in downstream probe design.
- New chemoselective transformations with plausible applicability to the
  target side-chain functionality or reactive-handle class.

The gate fails when the paper's primary novelty lies in the biological
system, device architecture, delivery format, or application context, and
its reactive chemistry is drawn from already-established classes. In that
case, cap the score at ≤ 6 even if the abstract mentions the target residue,
covalent bonding, or transferable reagents.

Methodology-first chemistry is explicitly in scope even when it is not
framed around the target residue, because the downstream use of this
pipeline includes harvesting structural inspiration from general synthetic
methodology, not only direct target-reactive literature.

## Scoring Criteria

### Score 9-10 (Exceptional Relevance)

- **DIRECT EVIDENCE:** Abstract explicitly describes chemical methodologies targeting identical or highly similar reactive sites
- **CONDITIONS:** Clear mention of mild, synthetically practical conditions
- **METHODOLOGY FOCUS:** Chemistry-first, synthetic methodology centered on target reactive site
- **STRONG POSITIVE SIGNS:** Chemoselective methodology, target-anchored functional-group transformation, transferable reagent/scaffold classes, site-selective modification

### Score 7-8 (High Relevance)

- **INDIRECT EVIDENCE:** Methodologies/structures/scaffolds applicable to similar reactive sites, even if not under final-use conditions
- **FULL-TEXT LIKELIHOOD:** Title/abstract/journal strongly suggest the full article will contain target-reactive motifs, transferable warheads, activated partner classes, precursor motifs, or mechanistic details
- **MECHANISTIC COMPATIBILITY:** Strong rationale suggests the mechanism could be adapted to milder conditions
- **STRUCTURAL RELEVANCE:** Compounds or reaction types closely analogous to target reactive handle
- **LATENT FULL-TEXT RELEVANCE:** Paper may contain substrates, intermediates, scaffold classes, activated motifs, or precursor logic aligned with target reactivity, **provided those elements are positioned as the paper's chemical contribution** — not merely as components supporting an application.
- **DOMAIN BALANCE (required):** The paper's chemistry contribution — not its biological or application context — must be what makes it relevant. Papers whose novelty sits in the application side fail the Novelty Attribution Gate and are scored ≤ 6, even when covalent bonding, target residues, or known reactive reagents are mentioned.

> Reasonable mechanistic and full-text-likelihood inference based on established reaction principles is acceptable; direct experimental evidence under highly aqueous conditions is NOT mandatory for scoring 7-8.

### Score 5-6 (Moderate Relevance)

- **STRUCTURAL INFORMATION:** Chemical structures or methodology classes potentially reactive but case for practical mild-condition applicability is incomplete
- **CONDITIONAL ADAPTABILITY:** May require substantial optimization, reformulation, or subset selection
- **LATENT BUT SECONDARY:** Useful clues exist but appear secondary or partial
- **FULL-TEXT UNCERTAINTY:** Useful details may exist but title/abstract evidence is only moderate

> May require extensive structure optimization or deep full-text inspection for reliable deployment.

### Score 1-4 (Low/No Relevance)

- **THEORETICAL LIMITATIONS:** Only low-confidence theoretical inference possible
- **CONDITION INCOMPATIBILITY:** Effective only under harsh conditions with no pathway toward mild chemistry
- **REACTION TYPE MISMATCH:** Mechanisms incompatible with target reactive site characteristics
- **INCIDENTAL LINK ONLY:** Relationship is peripheral, generic, or speculative
- **KINETIC LIMITATIONS:** Extremely slow (>days) or implausible for practical use

## Conservative Threshold

**Score ≥ 7** represents HIGH CONFIDENCE that the literature either directly supports, or very strongly suggests, methodologies or structures capable of enabling stable covalent bonding under mild, synthetically practical conditions with reasonable kinetics.

Do NOT assign ≥ 7 when the only connection is a weak downstream possibility with no concrete indication of target-reactive compounds or precursor motifs.

## Batch / Parallel Use

This prompt is safe to run in batches because each article is scored
independently from title, abstract, and journal name. For large searches,
split `pubmed_results.json["articles"]` into chunks of 20-50 articles and run
multiple independent calls when the host environment supports parallel model
execution or batch inference.

Return one JSON object per input article and preserve `pmid`, `doi`, `title`,
and the original input order within each chunk. After all chunks complete,
merge the outputs, sort or filter by `score >= 7`, and write the merged list to
`shortlist.json`. Do not let the score assigned to one article depend on the
presence or quality of another article in the same batch.
