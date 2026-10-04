# Run Atlas

A dependency-free Python 3.11+ knowledge-graph core and local explorer for the AI Atlas rare-disease challenge. Run these commands from the repository checkout.

For the connected graph, TopK search, Astra answers/extraction, review, recommendations and editable briefs, run `python3 -m atlas app --env-file .env --search topk --provider codex`. See the [connected workspace guide](docs/research-workspace.md) for dependencies and corpus setup. The main interface is `/explore`; `/research` redirects there. The commands below describe the explicit legacy explorer and fictional fixture.

```bash
python3 -m atlas demo
python3 -m atlas serve
```

Open **http://127.0.0.1:8765** for the full-screen artwork cover. Select the Atlas logo or visit **http://127.0.0.1:8765/explore** to use the research explorer. Search **Aurora** or its alias **AS-demo** to inspect the complete research route. Search **Delta** for the honest-gap case. The `demo` command's biomedical statements, people, organizations and assets are explicitly fictional software fixtures.

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

The homepage is a full-screen biological illustration. Enter Atlas to open the interactive graph at `/explore`: search nodes, rotate/pan/zoom, select an edge to inspect its evidence, or ask Atlas about the selected context. The Research drawer contains literature search, review, planning and briefs. `/records` retains the record browser.

Graph positions are a layout choice, not a biological similarity measure. Lines remain recorded assertions with visible inference, contradiction and review status. The cover artwork is conceptual; its provenance is saved in `atlas/web/images/connected-biology.txt`.

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

The connected local app uses real model calls and a focused, verified TopK index. Qualified scientific review, broader entity extraction, multi-user hosting and a held-out evaluation remain necessary. The working corpus is smaller than the harvested data; its coverage is explicit in the interface.
