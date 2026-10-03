"""Render a readable coverage report from the current acquisition manifests."""
import json
from harvest.core import ROOT, MANIFESTS, now, digest
from harvest.status import snapshot

def run():
    state=snapshot(); manifests={p.stem:json.loads(p.read_text()) for p in MANIFESTS.glob('*.json')}
    audit_path=ROOT/'data/harvest-audit.json'
    audit=json.loads(audit_path.read_text()) if audit_path.exists() else None
    lines=['# Harvest coverage and GRIN demonstration','',f'Snapshot: {state["generated_at"]}.','',
      'This report describes acquired source snapshots and recorded query results. It does not claim that every source is accessible, that a search retrieves all relevant research, or that source records are expert-validated biological conclusions. Large acquired files remain in the local workspace; Git contains code, checksummed manifests and small curated demo artifacts.','',
      '## Collection','',
      f'The manifests currently describe **{state["totals"]["records"]:,} normalized records** across **{len(manifests)} acquisition/reference collections**, with {state["totals"]["raw_bytes"]/1024**3:.2f} GiB of registered raw artifacts and {state["totals"]["normalized_bytes"]/1024**3:.2f} GiB of compressed normalized data. These totals mix entities, annotations, assertions, ontology stanzas, repeated source representations and query memberships. They are not counts of distinct patients, diseases or biological facts.','',
      'All 21 source entries in the original PDF are accounted for below. “Complete” always refers to the manifest’s declared file or query scope. “Permission required” and other gaps are explicit; no private registry or patient-level data was acquired.','',
      '| PDF ID | Source named in PDF | Acquisition status |','|---|---|---|']
    for item in state['pdf_source_coverage']:
        statuses='; '.join(f"{p['source']}: {p['status']}" for p in item['providers'])
        lines.append(f"| {item['id']} | {item['name']} | {statuses} |")
    lines+=['','## Source datasets','', '| Collection | Status | Normalized records | Manifest |','|---|---|---:|---|']
    for s in state['sources']:
        key=s['source'];lines.append(f"| {key} | {s['status']} | {s['records']:,} | [scope, provenance and gaps](../data/harvest-manifests/{key}.json) |")
    lines+=['','## Scope and interpretation','',
      '- ClinVar covers the acquired full variant summary and gene-condition release; full VCV archives are additionally acquired for the single-gene GRIN2A/GRIN2B subset. It is not a global VCV full-XML download.',
      '- The Europe PMC disease search uses every preferred name from the 7,200-disease vocabulary plus qualifying multiword aliases. The generic alias “the syndrome” is retained in the vocabulary but excluded from query execution; its superseded raw snapshots and quality correction are recorded. Results preserve article metadata and available abstracts; a vocabulary hit is a retrieval candidate, not an asserted disease association. PubMed generic and focused GRIN searches are retained separately.',
      '- The focused full-text queue is a declared relevance slice of GRIN citations with primary PMC identifiers. Article-specific license metadata, unsupported rights, unresolved records and failed retrievals are distinguished. Full-text acquisition is not complete merely because metadata exists.',
      f'- ClinicalTrials.gov includes generic searches and disease-name expansion; {len(manifests.get("clinicaltrials_gov",{}).get("disease_name_fallbacks",[]))} difficult name expressions use explicitly labeled broader fallback searches. Membership does not establish that a study concerns the specific named disease. NIH RePORTER uses recorded fiscal-year/query partitions. Trials, awards and proposed research do not establish efficacy.',
      '- Open Targets is a mapped rare-disease slice, with identifiers not resolved by the API retained as gaps. Aggregate associations and full underlying evidence are distinct datasets; only the focused GRIN disease set has its underlying source-native evidence harvested here.',
      '- MGI reports retain species, alleles, stock references and negated model assertions. A disease-level list of mouse genotypes does not identify a model of a particular human GRIN variant. Generic record rows and gene-level facilities require separate suitability checks.',
      '- Broad model/foundation source categories in the PDF are represented by declared structured reports and a bounded GRIN resource slice, not every organization on the internet. Indexed preprints are not complete dumps of the preprint servers.',
      '- OMIM, NORD, Global Genes and Orphanet expert resources require access or permission for the intended collection. EURORDIS access was blocked, Genetic Alliance US needs an export, and RareConnect is retained as retired-service metadata.','',
      '## GRIN reduced-function demonstration','',
      'The selected core contains GRIN2A G483R, A716T and D731N, and GRIN2B E413G, S541R and P553T. They have published Likely LoF classifications and linked primary assay measurements with study-specific wild-type comparators. C461F remains provisional; S541G and A639V are opposing controls; R540H remains unresolved. All scientific interpretation remains pending expert review.',
      '', 'The graph has 35 entities, 12 sources, 44 claims and 56 evidence records. The feature table preserves 57 study-specific assay rows without imputing missing measurements. An independently source-linked review queue includes 39 published variants and 14 newly assayed candidates from Myers 2023; it does not automatically admit them to the cohort.',
      '', 'The demo supports a concrete research-preparation task: inspect cross-gene functional evidence, distinguish provisional/opposing cases, identify the published registry and assay-service routes, and review a feasibility brief for shared observational measures. It does not solve the disorders, recommend a treatment, confirm participant eligibility or claim that any resource has agreed to collaborate.',
      '', '[Open local demo](http://127.0.0.1:18766/records) · [Reproduce the demo](grin-demo.md) · [Evidence and corrections](grin-evidence-notes.md) · [Research discussion brief](../data/curated/grin_research_proposal.json) · [Variant review queue](../data/curated/grin_functional_review_queue.json)','',
      '## Quality controls','',
      'The downloader checks response bytes, SHA-256 and resumable-download validators. Normalization preserves native fields, identifiers, negation and source attribution. Pagination audits compare provider counts, raw rows and distinct IDs; discrepancies remain explicit. Primary PubMed IDs are scoped to the article rather than accidentally extracted from its reference list. The GRIN table parser preserves image references and flags untranscribed values instead of representing image-only results as absent data.', '']
    if audit:
        stale=[s['source'] for s in audit['sources'] if s.get('manifest_sha256')!=digest(MANIFESTS/(s['source']+'.json'))]
        missing=sorted(set(manifests)-{s['source'] for s in audit['sources']})
        lines.append(f"Last [integrity audit](../data/harvest-audit.json): {audit['created_at']}; {audit['totals']['errors']} errors; deep record scan: {audit['deep_record_scan']}.")
        if stale or missing:lines.append(f'Audit freshness: {len(stale)} changed manifests and {len(missing)} new collections need a final audit. Do not treat the earlier audit as covering newer data.')
    else:lines.append('A final integrity audit has not yet been recorded.')
    lines+=['','Run `python3 -m unittest discover -s tests_harvest -q`, then `python3 -m harvest.audit`, `python3 -m harvest.status` and `python3 -m harvest.report` after acquisitions finish.','']
    path=ROOT/'docs/harvest-coverage.md';path.write_text('\n'.join(lines));print(path)

if __name__=='__main__':run()
