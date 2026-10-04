# Run the Atlas skeleton

A dependency-free Python 3.11+ knowledge-graph core and local explorer for the AI Atlas rare-disease challenge. Run these commands from the repository checkout.

```bash
python3 -m atlas demo
python3 -m atlas serve
```

Open **http://127.0.0.1:8765** for the full-screen artwork cover. Select **Enter Atlas** to open the graph workspace, or visit **http://127.0.0.1:8765/records** for the detailed disease index. Search **Aurora** or its alias **AS-demo** to inspect the complete research route. Search **Delta** for the honest-gap case. All bundled biomedical statements, people, organizations and assets are explicitly fictional software fixtures.

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

The homepage preserves the fullscreen biological artwork and its smooth entry transition. **Enter Atlas** opens `/explore`: a perspective-projected 3D graph with a compact search field and an **Ask Atlas** popup. Drag the canvas to orbit, Shift-drag to pan, drag individual nodes to reposition them, and scroll or pinch to zoom. Arrow keys rotate; + / − zoom; 0 fits the view. Gentle idle rotation pauses during interaction, selection, search, dialogs and chat. It respects reduced-motion preferences and can be disabled in graph options. The resting view has no counters, zoom toolbar or entity labels. Hover uses a short dwell and a stable pointer radius to reveal a label and ring without fading the graph. Clicking chooses the nearest visible point, consistently with hover, and reveals its neighborhood with a short fade. Search centering eases into place and is interrupted by dragging or zooming; reduced-motion preferences disable these transitions. A shared blue, amber, jade, violet, and rose palette distinguishes record types across points, connections, and the legend. Depth adjusts opacity and line weight; cached halo sprites emphasize hubs without per-frame gradient work. Search and selection use coloured rings. The layout uses reproducible, irregular 3D cluster seeds and varied spring lengths to avoid repeated radial rosettes. Recorded relationships still drive the relaxation. Positions are a graph layout, not biomedical similarity. Canvas batches graph drawing once per animation frame; an SVG layer retains keyboard-accessible nodes and evidence targets. During dragging, SVG hit areas update on release instead of on every pointer event. Search highlights every matching entity as you type, fades non-matches, and prioritizes exact labels or aliases. Enter selects and centers the first result; Escape clears the search.

`python3 -m atlas demo` now builds a reproducible demonstration with 471 entities and 894 assertions using `atlas/demo.py`. The original 23-entity acceptance fixture remains unchanged. Every added assertion has an explicitly fictional source excerpt, and the dataset retains its synthetic provenance in the API, evidence and detailed workspace. The larger demo is never mixed into imported production data.

Edges represent the bundle's actual assertions. Dashed edges are inferred; rust edges indicate counter-evidence or negated assertions. Selecting an edge or a chat citation opens the original source excerpt, context, locator and review status. **Graph options → Open evidence workspace** retains the prior detailed explorer at `/records`, with candidate comparison, asset routes and source libraries.

**Ask Atlas** is a local, deterministic graph lookup, not a language-model integration. It supports entity descriptions, evidence, mechanism comparisons, counter-evidence and evidenced research assets. Answers preserve the conservative reasoner's statuses and link to claim IDs. Evidence follow-ups can retain the preceding answer's claim scope. Unsupported questions receive an explicit scope limitation. No chat text is sent to an external AI service.

Voice dictation uses the browser's SpeechRecognition API when available. A short disclosure precedes activation because the browser may use an external speech service. Speech fills a draft; the user presses **Ask** to submit. Permission errors and unavailable speech engines fall back to typing. Closing chat or leaving the page stops recognition. Microphone transcription requires testing on the user's browser/device; no live microphone recording was performed during implementation.

The original logo, Instrument Sans and conceptual illustration are preserved. The image generation prompt is in `atlas/web/images/connected-biology.txt`. Design interaction references: [Obsidian Graph view](https://obsidian.md/help/plugins/graph); voice capability reference: [MDN SpeechRecognition](https://developer.mozilla.org/en-US/docs/Web/API/SpeechRecognition).

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

## Lovable migration

Run `python3 scripts/package_lovable.py` to build `dist/atlas-lovable-migration.zip`. The archive includes the exact interface and assets, reference Python implementation, synthetic demo bundle, tests, 13 captured API parity cases, and a migration brief. It contains no environment files, credentials, harvested datasets or local databases. This is a migration package, not a deployed app: Lovable requires a project created on its platform, and the Python API must either be ported into the project's native server stack or hosted separately. Publish only after verifying the migrated behavior and appearance.
