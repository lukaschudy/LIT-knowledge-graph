# Run the Atlas skeleton

A dependency-free Python 3.11+ knowledge-graph core and local explorer for the AI Atlas rare-disease challenge. Run these commands from the repository checkout.

```bash
python3 -m atlas demo
python3 -m atlas serve
```

Open **http://127.0.0.1:8765** for the full-screen artwork cover. Select the Atlas logo or visit **http://127.0.0.1:8765/explore** to use the research explorer. Search **Aurora** or its alias **AS-demo** to inspect the complete research route. Search **Delta** for the honest-gap case. All bundled biomedical statements, people, organizations and assets are explicitly fictional software fixtures.

If `data/atlas.sqlite` already exists, `demo` stops to protect its contents. Use a separate database (`--db /tmp/atlas-demo.sqlite`) or explicitly replace the existing dataset (`demo --replace`). `serve`, `search`, `explore`, `stats` and `export` accept the same `--db` option.

## Included

- Typed entities, contextual claims, supporting/contradicting evidence, source metadata and search coverage.
- Transactional SQLite storage; canonical JSON, JSON-LD and Cytoscape exports.
- Conservative variant-effect matching and evidence-qualified research assets/partners.
- Source-span validation for proposed AI extractions; model-independent prompt template.
- Offline HPOA import preserving negative assertions, onset and frequency.
- A read-only local explorer with evidence inspection and explicit uncertainty.
- Automated acceptance tests including a supported journey and misleading neighbors.

## Explorer

The homepage is an edge-to-edge biological illustration with only the Atlas logo. The logo opens `/explore`, which retains the illustrated introduction and research index. The split introduction and focused navigation draw on TopK, with earlier green visual direction from Definite and Halmos Labs. The original Atlas mark is preserved. Instrument Sans, found in the user's `thinkingsquared` project, is bundled locally with its OFL license; Plex Mono remains for technical identifiers.

The introductory artwork is conceptual, not microscopy or evidence. Its built-in image generation prompt and provenance are saved in `atlas/web/images/connected-biology.txt`. The primary button moves keyboard focus to the disease index; “How it works” opens the guide.

Select a disease, then a candidate in the connection list. **Connection map**, **Evidence**, and **Research assets** stay synchronized with that selection. Map relationships open the claim's evidence sheet; map entities open their linked records. Source and asset libraries are available in the masthead. In narrower windows, candidates form a horizontal strip; the map scrolls horizontally on phones.

Graph paths come from the reasoner's recorded claim IDs. A displayed path is not automatically supported: unknown effects, inferred claims and contradictory evidence retain their review or rejection state. The disease index summarizes recorded mechanisms, effects and evidence counts; these are source assertions, not clinical compatibility judgments.

## Command line

```bash
python3 -m atlas validate data/fixtures/atlas-demo.json
python3 -m atlas stats
python3 -m atlas search 'AS-demo'
python3 -m atlas explore demo:disease-a
python3 -m atlas export --format jsonld --output /tmp/atlas.jsonld
python3 -m atlas export --format cytoscape --output /tmp/atlas-cytoscape.json
python3 -m atlas ingest /path/to/normalized-bundle.json --db /tmp/real-atlas.sqlite
```

`ingest` validates the complete bundle before replacing anything. Existing databases require `--replace`. It does not merge identities or promote hypotheses into facts.

Convert a locally downloaded HPO annotation snapshot, supplying its actual source version, retrieval date and reuse terms:

```bash
python3 -m atlas convert-hpoa /path/to/phenotype.hpoa \
  --source-url https://your-verified-source.example/phenotype.hpoa \
  --retrieved-at 2026-10-03 \
  --source-version YOUR_PINNED_RELEASE \
  --license YOUR_VERIFIED_TERMS \
  --output /tmp/hpoa-bundle.json
python3 -m atlas validate /tmp/hpoa-bundle.json
```

The URL above is a placeholder; the adapter performs no downloads. HPOA supplies phenotype annotations, not mechanism compatibility or asset ownership. A phenotype-only import is expected to produce no supported action route.

## Verify

```bash
./scripts/check-atlas.sh
```

The Python tests use `unittest` from the standard library. Tests validate source grounding, typed endpoint references, atomic replacement, alias resolution, export provenance, HPO qualifiers, positive routes, opposing effects, missing evidence/owners, and contradictions. They establish software behavior on fixtures; they do not measure biomedical accuracy.

## Architecture and handoff

- [Architecture, research rationale, and deliberate limits](docs/architecture/atlas.md)
- [One-minute demonstration and impact measurement plan](docs/architecture/demo.md)
- [Machine-readable bundle schema](schemas/atlas.schema.json)
- [Extraction prompt](prompts/claim-extraction.txt)
- [Existing challenge review](docs/pdf-review.md)

The skeleton has no live model call, biomedical bulk dataset, credentials, calibrated clinical predictions or production deployment. The next milestone is a small real disease cluster with expert-reviewed claims, an actual research asset and verified organizations. An OpenAI extraction integration is a separate next increment; the current prompt alone does not satisfy the challenge's OpenAI prize requirement.
