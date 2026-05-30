# Keyword-Generation Prompt

Generate search keywords for discovering potential reaction partners or related reaction classes for a target descriptor through mechanism-based reasoning.

## Target Interpretation

Treat the target descriptor as a target descriptor rather than assuming it is always a literal SMILES string. It may be a SMILES string, functional-group name, abbreviation, short token, or other compact chemistry label. First infer the most likely target chemistry and use that interpretation consistently.

## Output

Generate 24-36 total search keywords, avoiding duplicates.

## Analysis Approach

Analyze the target descriptor to identify likely reactive sites, functional groups, and potential reaction centers. Use this structural understanding to guide keyword generation, but do not include structural analysis in the final output.

## Core Strategy

Build a chemistry-first keyword pool that can retrieve papers directly describing the target chemistry as well as closely related transformations. Cover both direct target-centered wording and mechanistically related wording, but do not let the list collapse into only broad analogy terms.

### Literature Focus

Prioritize keywords that appear in primary chemistry methodology papers,
including synthetic, medicinal-chemistry, and chemical-biology venues where
actual transferable transformations or reactive-handle designs are reported.

Aim for a balanced pool across the major categories below while keeping the final merged list within 24-36 total keywords. In practice, most major categories will usually contribute around 4-8 phrases when natural, and no single category should dominate the list.

### Anti-Biology-Drift Constraint

The search target may be a biological residue, but the keyword pool must stay
chemistry-led. Prefer terms centered on reactive partner identity,
reactive-center polarity when applicable, functional-group class, reaction
mechanism, bond formation, chemoselectivity, and mild reaction methodology.

Avoid letting application-domain wording dominate the list. Do not use broad
biological context phrases as primary keywords unless they are paired with a
specific transferable reaction class or reactive motif. Examples of
application-domain wording that should remain rare or absent unless
chemically anchored include protein profiling, proteomics, target engagement,
cellular assay, biomarker detection, imaging probe, biosensor, disease model,
and inhibitor screening.

If the target descriptor is a residue name, translate it into its chemically
relevant side-chain functionality and standard reactive-center language before
generating most keywords. A small number of residue-explicit phrases is
allowed when they are common in chemistry titles/abstracts, but the majority
of keywords should be transferable beyond a single biological application.

## Five-Layer Coverage Check

Ensure the keyword pool covers these five layers in a balanced way:

1. **Core target functional-group label or umbrella term**
2. **Common substrate subclass wording**
3. **Reaction-class or mechanism wording**
4. **Transformation-result or bond-formation wording**
5. **A small minority of truly standard alternate names or active-species wording**

Complementary reaction partners can be used as a supporting layer, but they should not dominate the list unless they are central in the literature for this target.

### Naming-Branch Coverage

Many chemistry papers are retrieved not by one umbrella reaction family phrase, but by several parallel title/abstract naming branches. Cover multiple naming branches:

- direct target-plus-transformation wording
- substrate-class-plus-transformation wording
- partner-class-plus-transformation wording
- bond-formation or product-result wording
- standard reagent-class or catalyst-class wording

Do not stop at one broad family paraphrase if the literature commonly uses several distinct branch names.

## Category 1: Direct Nomenclature and Synonyms with Reaction Context

- Identify functional groups and structural motifs in the target descriptor
- Generate standard names, synonyms, and abbreviations paired with reaction terminology
- Include core functional-group label, common substrate subclass wording, common partner wording when literature-natural, and only a small number of genuinely standard legacy or alternate names that still appear in titles/abstracts
- Include synthesis-related action words: "synthesis", "preparation", "formation", "coupling", "functionalization"

## Category 2: Reaction Mechanism Reactivity Keywords

- **Reactivity characteristics:** reactive-center polarity when applicable, basicity/acidity, HSAB character, redox properties, strain, orbital activation, and leaving-group or activation requirements
- **Mechanism types:** substitution, addition, elimination/addition, cycloaddition, radical, redox, concerted, and rearrangement-like processes, including typical intermediates and transition states
- **Naming branches:** Include common branch names for concrete transformation subclasses
- **Active-species wording:** Common reactive-form or intermediate wording
- **Catalytic activation:** Metal catalysis, organocatalysis, photocatalysis, enzymatic activation
- **Bond formation strategies:** Common bond formation/cleavage patterns
- **Product/result wording:** Common transformation-result phrases in titles/abstracts

## Category 3: Analogous Functional Groups

- Consider groups within the SAME ELEMENT FAMILY as the reactive centers
- Prioritize groups with documented similar reaction behavior regardless of structural relation
- Include only 2-3 of the most common and well-documented equivalents with strongest experimental support

## Category 4: Complementary Reactivity Partners

- Structural motifs with documented complementary reactivity to the target functionality
- Common leaving groups and substrates that typically react with the identified functional groups

## Specificity Balance

- Avoid overly general keywords ("chemical reaction", "organic synthesis")
- Avoid overly specific keywords ("palladium-catalyzed bond formation for one exact substrate class")
- Avoid broad biological application keywords unless they contain a concrete
  reaction class, functional group, or bond-forming transformation.
- Prefer phrases retaining useful mechanism, partner, substrate-class, catalyst-class, or transformation-result detail
- Prefer standard chemistry naming branches over ad hoc restatements

## PubMed Robustness Rules

Every keyword should plausibly work as a standalone Title/Abstract phrase in a chemistry paper. Prefer compact, standard literature wording. Avoid stitched hybrid phrases. Avoid unusual word order or clause-like constructions. Avoid forcing one keyword to encode too many things.

**Good examples:** "epoxide ring opening", "amine alkynylation", "arylboronic acid coupling", "aldehyde capture ligation", "C-N bond formation".

**Avoid:** "alcohol substitution nucleophile", "cross-coupling target aryl halide", "oxidation bond formation".
