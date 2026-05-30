# Report-Composition Prompt: Academic Report Composition

## Purpose

Turn the enriched `candidates.json` (post `smiles_to_image.py`) into a
polished, paper-style Markdown report. The report is the deliverable a
chemist will read; the JSON remains the machine-readable audit trail.

## Required inputs

- `candidates.enriched.json` — structure-extraction prompt output after RDKit
  validation and rendering, JSON Schema validation, and candidate-contract
  validation.
- `keywords.txt` — exact keyword set used for PubMed.
- `pubmed_results.json` — raw search hits and filtering metadata.
- `shortlist.json` — articles kept after the relevance-scoring prompt.
- `pdfs/download_log.json` — PDF acquisition statistics and failures.
- `paper_metadata` for each referenced article.
- `target_residue` — e.g. `Cysteine`.
- `search_date` — ISO date string shown in the header.

## Writing style

Write an academic report, not a structured form. That means:

- Running prose in first-person-plural or third-person academic voice
  (`we`, `Smith and co-workers`, `Lanning et al.`). When attributing work to
  a paper, **always use the real first-author surname** drawn from
  `source_authors`; never write `"the authors of ref. N"` or any
  ref-number-only attribution — it is reserved for the superscript itself.
- Inline citations as ACS-style superscript numbers (`¹`, `²`, …, or
  `<sup>1</sup>`). Every specific fact cited to the literature gets a
  superscript. Group consecutive references with commas: `²,⁴`.
- Figures for structures with numbered captions (`**Figure 1.** ...`).
- A single **References** section at the end with full ACS bibliographic
  entries in numbered order matching the superscripts used in text.

Do NOT do the following — they make the report read like a database
dump instead of a paper:

- No bullet lists of `field: value` pairs describing candidates.
- No `Confidence: 8/10` lines anywhere in the body.
- No `Evidence Quote: "..."` pseudo-fields. If a quote supports a claim,
  work it in as a normal sentence with a superscript citation.
- No headings named `Novelty Justification` or `Reactivity Analysis`.
  Discuss these points in prose under Results and Discussion.
- No raw JSON field names (`canonical_smiles`, `smiles_confidence`, …) in
  the body. SMILES themselves are fine as inline code spans where a
  chemist would want them.

## Cross-paper merging

When two or more candidates share the same `canonical_smiles`, merge them
into a single candidate subsection in §3.2. Cite every supporting paper in
the introductory sentence of that subsection and list every one in the
References. In the narrative, note that the finding is corroborated across
independent reports — this is a positive signal for experimental priority.

If two candidates have different canonical SMILES but clearly represent the
same mechanistic family (e.g. substituted α-cyanoenones with different
peripheral groups), do not merge the SMILES; instead, discuss them together
in prose under a shared subsection heading.

## Candidate filtering for the body vs appendix

- `validation_status == "ok"` **and** `smiles_confidence ≥ 6` →
  full subsection under §3.2 Results and Discussion.
- `validation_status == "ok"` **and** `smiles_confidence < 6` →
  listed in **Appendix C – Low-Confidence Candidates Needing Manual
  Review**. One short paragraph each, citing the paper and noting what
  specifically was uncertain (stereochemistry, tautomer, ring connectivity,
  etc.). Include the uncertain SMILES in inline code but omit the figure.
- `validation_status != "ok"` (missing or invalid SMILES) →
  drop from the report entirely; they remain only in the JSON.
- `manual_review_status != "human_confirmed"` →
  keep the candidate out of any publication-facing priority claim. If the
  user explicitly wants a hypothesis-only draft, discuss it with guarded
  language and state that it awaits manual structure/evidence confirmation.

When `reactivity_confidence < 6`, keep the candidate in the body but use
hedged language (`suggestive evidence`, `tentatively`, `pending independent
confirmation`) rather than definitive claims.

## Report skeleton

```markdown
# Novel {TargetResidue}-Reactive Handles Identified from Recent Chemistry Literature
*Survey date: {search_date}*

## Abstract
2–3 sentences. State the scope of the search, the number of articles
processed, and the count and mechanistic families of the novel candidates
reported. No citations, no numbers beyond what the summary needs.

## 1. Introduction
1–2 paragraphs setting up (a) why {TargetResidue} is targeted in covalent
probe design, (b) the shape of the known warhead landscape for that
residue (cite a couple of reviews or canonical method papers if
available), and (c) the gap or motivation driving this survey. Use
superscript citations.

## 2. Methods
A single dense paragraph (or two at most) covering:

- Database and query strategy (N keywords, five-layer coverage).
- Filters applied (publication type ≠ review / systematic-review /
  meta-analysis; page count ≤ max_pages; score threshold).
- Known-warhead exclusion list (cite KNOWN_WARHEADS with count).
- Full-text source policy (only acquired PDFs are used for downstream
  extraction; papers without a valid PDF remain in the acquisition audit and
  are excluded from candidate extraction).
- Structure extraction workflow (PDF figures and schemes as the evidence
  source; structure locators and optional screenshot crops retained in the
  audit trail; RDKit canonicalisation and rendering; post-hoc JSON Schema and
  workflow-contract validation).

No bullet lists here. Running prose only.

## 3. Results and Discussion

### 3.1 Search statistics
One short paragraph with: hits across keywords, unique after dedup,
shortlisted at the score threshold, usable PDFs acquired, acquisition
failures, novel candidates that passed the novelty
filter. Report counts inline without a table.

### 3.2 Novel candidates

Subsections in order of decreasing {reactivity_score} (ties broken by
earlier publication date). For each candidate:

#### 3.2.N {descriptive-name}
One or two running-prose paragraphs covering:

- What the authors reported, with the reactive fragment called out
  explicitly (inline SMILES in code span) and the parent structure
  summarised.
- The mechanism under the requested or plausible probe-use conditions, the
  kinetics or selectivity data the authors measured, and the conditions used.
  Quotes from the paper can be folded in as normal sentences; every specific
  claim carries a superscript citation.
- Why this is considered novel relative to known warhead classes — what
  is different electronically, sterically, or mechanistically. This is
  the {novelty_reasoning} content rewritten as argumentative prose.
- If the candidate was reported in more than one paper in the survey,
  note the independent support.

Immediately below the prose, embed the structure figure:

    ![Figure N](images/candidate_0NN.png)

    **Figure N.** Reactive fragment of the {descriptive-name} identified by
    {first-author} et al.{superscript}. Canonical SMILES: `{canonical_smiles}`.

Use `reactivity_confidence` to calibrate hedging, not to print a score.

## 4. Conclusion
1–2 paragraphs. Surface structural or mechanistic patterns across the
candidate set. Name the candidates that deserve experimental priority
(those with the strongest kinetics and cleanest probe-relevant evidence) and
the ones that are promising but need more work. Be explicit about the
limitations of the survey (acquisition failures, low-confidence
transcriptions, abstract-only fall-through).

## References
Numbered list matching the superscript citations in order of first
appearance. **Strict ACS format** — see the rules immediately below.

### Reference formatting rules (hard constraints)

For every entry, follow these rules in order:

1. **Source of metadata.** Pull `source_authors`, `source_journal`,
   `source_year`, and any pagination from the candidate record in
   `candidates.enriched.json`. If a field is missing on the candidate,
   look the paper up by DOI in `shortlist.json`, and if still missing in
   `pubmed_results.json` (both files carry the full PubMed author list,
   ISO journal abbreviation, year, and page range). Do **not** invent
   metadata and do **not** emit any placeholder author, title, or year.

2. **No placeholder strings, ever.** The strings `Authors of ref. N`,
   `Authors of ref.`, `Author et al.` (with a literal `Author`), `unknown`,
   `n/a`, or any other stand-in for missing metadata are forbidden in the
   reference list. If after step 1 a required field is still missing,
   drop the candidate from the report rather than emit a degraded
   reference.

3. **Journal-article format** (the common case):

   ```
   N. Author, A. A.; Author, B. B.; Author, C. C. *Journal Abbr.*
   **Year**, *Volume*, StartPage–EndPage. DOI: 10.xxxx/yyyy.
   ```

   - Use the ISO journal abbreviation from `source_journal` (PubMed already
     supplies it in that form; do not re-abbreviate).
   - List **every** author from `source_authors`, in original order,
     separated by `; `. Do not use `et al.` in the reference list. (You
     may use `et al.` only in the inline prose, never here.)
   - Page range: prefer `StartPage–EndPage` if both are known. If the
     paper is an electronic-only article identified by an article number
     (e.g. `e202518939`, `2401234`), write that single locator in place
     of the page range with no en-dash. Volume may then be omitted.
   - Always end with `DOI: <doi>.` exactly once.

4. **Database / software citation format.** The known-warhead exclusion
   library is a database, not a primary article. Cite it as:

   ```
   N. PDBcov / CovBinderInPDB Database; known-warhead exclusion list
   v1.0.0, {TargetResidue} subset ({class_count} classes); New York
   University. https://yzhang.hpc.nyu.edu/CovBinderInPDB (accessed
   {search_date}).
   ```

   Use the actual version string from `data/known_warheads.json` and the
   actual class count for the surveyed residue. Place this entry only if
   it was actually cited via a superscript in the body.

5. **One superscript ↔ one numbered entry.** Every superscript that
   appears in the body must have exactly one matching numbered entry, in
   first-appearance order. Do not number entries that were not cited.

### Worked example

```
1. Backus, K. M.; Correia, B. E.; Lum, K. M.; Forli, S.; Horning, B. D.;
   González-Páez, G. E.; Chatterjee, S.; Lanning, B. R.; Teijaro, J. R.;
   Olson, A. J.; Wolan, D. W.; Cravatt, B. F. *Nature* **2016**, *534*,
   570–574. DOI: 10.1038/nature18002.

2. Gehringer, M.; Laufer, S. A. *J. Med. Chem.* **2019**, *62*,
   5673–5724. DOI: 10.1021/acs.jmedchem.8b01153.

3. Petri, L.; Ábrányi-Balogh, P.; Tímea, I.; Pálfy, G.; Perczel, A.;
   Knez, D.; Hrast, M.; Gobec, M.; Sosič, I.; Nyíri, K.; Vértessy, B.;
   Pande, V.; Gobec, S.; Keserű, G. M. *Angew. Chem. Int. Ed.* **2025**,
   e202518939. DOI: 10.1002/anie.202518939.

4. PDBcov / CovBinderInPDB Database; known-warhead exclusion list v1.0.0,
   Cysteine subset (69 classes); New York University.
   https://yzhang.hpc.nyu.edu/CovBinderInPDB (accessed 2026-05-18).
```

## Appendix A — Keyword Set
The exact keywords fed to PubMed, one per line, grouped by the five-layer
coverage category.

## Appendix B — Acquisition Failures
A compact list: DOI, title, publisher, reason a usable PDF could not be
retrieved. Mirrors what is in `download_log.json` but human-readable.

## Appendix C — Low-Confidence Candidates Needing Manual Review
One short paragraph per low-confidence candidate. State the paper,
briefly describe the reactive motif in words, include the uncertain
SMILES inline, and note exactly what was hard to read (stereochemistry,
tautomer, ring fusion, fragment boundary, …). No images here.
```

## File layout expected by the caller

```
report.md                       ← this prompt's output
candidates.enriched.json        ← structure-extraction + smiles_to_image.py output
images/candidate_001.png ...    ← rendered structures referenced from report.md
keywords.txt                    ← exact keyword set
pubmed_results.json             ← raw search results + filtering metadata
shortlist.json                  ← shortlisted papers used for acquisition
pdfs/                           ← acquired PDFs and download_log.json
```

## Hard constraints

- Do not invent citations. Every superscript must map to a paper already
  present in `candidates.enriched.json`'s `source_*` fields.
- Do not emit placeholder author lists. Strings such as `Authors of ref. N`,
  `Author et al.`, `Unknown`, or any other stand-in for missing
  `source_authors`, `source_journal`, or `source_year` are forbidden in the
  References section. Pull metadata from `candidates.enriched.json` and,
  for any missing field, look up by DOI in `shortlist.json` or
  `pubmed_results.json`. If after those lookups a required field is still
  missing, drop the candidate from the report rather than degrade the
  reference.
- Do not emit any structure figure that has no corresponding file in
  `images/`. If `image_path` is missing for a candidate, drop the image
  line and mention the structure by SMILES in inline code.
- Do not hard-code residue-specific reasoning that is not supported by a
  cited paper. If the survey turned up no strong evidence for a mechanistic
  pattern, say so; do not overclaim.
- Do not describe a candidate as publication-ready unless
  `manual_review_status` is `human_confirmed`.
