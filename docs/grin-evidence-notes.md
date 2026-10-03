# GRIN2A/GRIN2B reduced-function evidence set

`data/curated/grin_functional_evidence.json` is a small, reviewable evidence set for a research/demo cluster. It is not a complete GRIN variant catalog, a clinical classification, or a treatment recommendation. It preserves reported cDNA/protein notation and transcript accession only where a cited source supplies one; it does not guess a transcript. All ten entries have assay evidence, but only entries with `strict_reduced_function_inclusion: true` are proposed as reduced-function leads.

## Selection and interpretation

The six strict leads classified as **Likely LoF** by the integrated multi-assay framework of Myers et al. (2023) are GRIN2A p.Gly483Arg, p.Ala716Thr, and p.Asp731Asn; and GRIN2B p.Glu413Gly, p.Ser541Arg, and p.Pro553Thr. GRIN2B p.Cys461Phe is retained as a **provisional Possible LoF** case, excluded from the six-variant core. The JSON also includes GRIN2B p.Ser541Gly (same-residue opposing-direction comparator, classified Possible GoF), p.Ala639Val (GoF comparator supported by M3 functional work), and p.Arg540His (unresolved/indeterminate comparator). These three and the provisional case have `strict_reduced_function_inclusion: false`.

“LoF” here means the source authors' functional classification based on their assay framework. It is separate from clinical pathogenicity. Clinical association fields summarize reported phenotypes and cite their literature location; they do not prove that the measured channel effect causes a particular severity. A single reduced parameter is not treated as net loss of function. ClinVar and variant consequence are not used to infer receptor functional direction.

The 2016 Swanger study supplies quantitative agonist potency, deactivation, and peak-current measurements for several entries. Its Table 3 synaptic/non-synaptic charge-transfer ratios are explicitly identified as author-calculated predictions derived from experimental parameters, not direct physiological measurements. Platzer et al. provide additional GRIN2B functional and clinical context for p.Ser541Arg. Xie et al. measure pre-M1 variants, including p.Pro553Thr and p.Ser541Gly, and report measured component phenotypes alongside modeled charge-transfer estimates. Xu et al. provide functional measurements for M3 variants including p.Ala639Val. The engineered triheteromeric receptor paper by Han et al. is included only as context for the p.Ala639Val comparator: it studies antagonist pharmacology and agonist potency in engineered receptor configurations, not a full LoF/GoF charge-transfer classification.

## Data and provenance

Each variant record carries one or more functional-evidence objects with the paper identifier, exact table/row locator, assay/model, measured parameter, native unit, sample size where reported, and wild-type comparator. Values are represented as strings to preserve the source's notation (including uncertainty). Author-derived classifications and charge-transfer outputs are kept distinct from raw measurements. Table values are transcribed, not recomputed. Clinical features are paraphrased or compact labels; no long source passages are reproduced.

Primary references:

- Swanger et al. 2016, PMID 27839871, DOI [10.1016/j.ajhg.2016.10.002](https://doi.org/10.1016/j.ajhg.2016.10.002), [PMC5142120](https://pmc.ncbi.nlm.nih.gov/articles/PMC5142120/).
- Platzer et al. 2017, PMID 28377535, DOI [10.1136/jmedgenet-2016-104509](https://doi.org/10.1136/jmedgenet-2016-104509), [PMC5656050](https://pmc.ncbi.nlm.nih.gov/articles/PMC5656050/).
- Chen et al. 2020, PMID 32712275, DOI [10.1016/j.neuropharm.2020.108247](https://doi.org/10.1016/j.neuropharm.2020.108247), [PMC7554152](https://pmc.ncbi.nlm.nih.gov/articles/PMC7554152/). Secondary synthesis used only to cross-check clinical/variant labels and references, not as the origin of assay values.
- Myers et al. 2023, PMID 37369021, DOI [10.1093/hmg/ddad104](https://doi.org/10.1093/hmg/ddad104), [PMC10508039](https://pmc.ncbi.nlm.nih.gov/articles/PMC10508039/).
- Xie et al. 2023, PMID 37000222, DOI [10.1007/s00018-023-04705-y](https://doi.org/10.1007/s00018-023-04705-y), [PMC10641759](https://pmc.ncbi.nlm.nih.gov/articles/PMC10641759/).
- Xu et al. 2024, PMID 38538865, DOI [10.1007/s00018-023-05069-z](https://doi.org/10.1007/s00018-023-05069-z), [PMC10973091](https://pmc.ncbi.nlm.nih.gov/articles/PMC10973091/).
- Han et al. 2022, PMID 35110392, DOI [10.1124/jpet.121.001000](https://doi.org/10.1124/jpet.121.001000), [PMC11046977](https://pmc.ncbi.nlm.nih.gov/articles/PMC11046977/).

## Limits and review status

This is a targeted first slice, not a literature-complete extraction: it focuses on the cited primary papers and their tabulated variants, and does not claim coverage of every GRIN2A/GRIN2B variant, every published functional experiment, or every supplementary dataset. The clinical evidence is not independently re-adjudicated. Functional assays are mostly recombinant systems and may not capture native neuronal receptor composition; diheteromeric and triheteromeric receptor results may differ. Review status is `machine_curated_expert_review_pending`; external domain review remains outstanding.

## Verification corrections

The original Xie 2023 Table 1 prints c.1621A>C alongside p.Ser541Gly, whereas the ClinVar archive VCV001708206 lists NM_000834.5:c.1621A>G for p.Ser541Gly. The source notation is preserved with an identity-discrepancy flag; no automatic allele merge is permitted. The protein-level assay remains an opposing-function control.

The Xie 2023 wild-type controls were checked against its own Tables 2 and 3 and corrected to the study-specific values (for example deactivation 1061 ± 91 ms, n=16); controls from the distinct Xu 2024 study must not be substituted. S541R charge-transfer values are explicitly attributed to Xie, separately from the Platzer assay measurements.

## Expansion and supplemental coverage

The separate `grin_functional_review_queue.json` records all 39 GRIN2A/GRIN2B protein variants explicitly named in the Myers Discussion category list, including ten expression-limited Likely LoF cases. It also preserves 14 newly assayed Table 1 candidates. Table 6 provides readable Indeterminant calls for I150V and E657D; twelve other final-call cells use images and remain untranscribed. No queue entry is automatically admitted to the selected cohort.

The Myers supplemental PDF was acquired through Europe PMC and retained with checksums and nine pages of layout text. Tables S3–S5 support further assay review; the PDF remains the authoritative layout. Across the seven selected article HTML pages, 31 table rows contain images. The table dataset retains their URLs, alt text and cell spans and explicitly flags untranscribed image content. Blank extracted text is not evidence that the source lacked a result.
