Atlas on Cloudflare

Build the current frontend and the reviewed real GRIN cluster:
  python3 scripts/build_cloudflare.py

Run Cloudflare locally (install uv and Node.js first):
  cd deploy/cloudflare
  uv run pywrangler dev --port 8788

Deploy application updates without changing domain routes:
  uv run pywrangler versions upload --message "Describe the update"
  uv run pywrangler versions deploy <returned-version-id>@100% --yes

For first-time setup with route/DNS permissions:
  uv run pywrangler deploy

The build verifies the committed annotation receipt, then publishes the real
35-node graph and all 340 reviewed observation records / 53 annotation claims.
It refuses synthetic fixtures and preserves the previous graph file unchanged.
The graph's effect assertions and variant summaries use the reviewed reference;
older scalar functional summaries are removed from the derived deployment.
The build copies only allowlisted web assets, the shared read-only API, graph
reasoner, annotation lookup, reviewed metadata and bounded source spans. It does
not publish local SQLite files, complete harvested papers, environment variables,
or arbitrary repository contents. Rebuilding requires the matching local frozen
source snapshot for the cited table cells and short supplement-row excerpts.
API logic is shared with the local Python server in atlas/http_api.py.

Production pages:
  /explore — real graph and Ask Atlas
  /cluster — 10 variants, 340 observations, experimental comparisons and sources
  /cluster?variant=GRIN2B%3Ap.Ser541Arg — open a specific reviewed protein variant

Ask Atlas uses deterministic source-annotation lookup for these variants. It is
not an LLM chat or a replacement for the separate TopK literature-search pilot.
Long source passages remain in the reviewed local snapshot; deployed evidence
shows bounded table/supplement excerpts, complete citation locators and paper links.

The production Worker is varentik-atlas in the user's Cloudflare account.
The active custom domain is atlas.varentik.com.
The existing OAuth profile can upload Workers but lacks DNS/route scopes;
manage custom domains and routes through the signed-in Cloudflare dashboard.

Root-domain maintenance is a separate Worker: varentik-maintenance.
The active route varentik.com/* temporarily overrides the original landing Worker
without replacing or deleting it. Removing only that route restores the original
site. Do not use *.varentik.com/*, which would also hide Atlas and other subdomains.

Initial published Atlas version: afea32e7-07c4-4df5-a999-f698b69754e4
Last synthetic deployment before the reviewed-data release:
  d744f6ea-3cc8-410e-9a5a-bc6e6ebcae0e
Reviewed GRIN deployment (100% traffic; production browser checks passed):
  7337a382-13f2-4951-a2b9-4a24bc9ecaa3
Release provenance and verification: deploy/cloudflare/release.json
Maintenance version: 32f3629f-473d-40ec-9bbb-9e3139cc10a1

To restore the main site, remove the varentik.com/* route from the Cloudflare
zone Workers Routes page and from deploy/maintenance/wrangler.jsonc. The
varentik-landing Worker and its apex custom-domain binding remain intact.

Dense graph release (2026-10-04):
The graph now includes the fixed public 10,000-node HGNC source projection and
35 reviewed GRIN nodes. Source relationships remain explicitly unreviewed.
The snapshot is data/curated/hgnc_dense_snapshot.json.gz; the read-only API supports
bounded graph paging, neighborhoods, entity search and source provenance links.
It contains HGNC gene/protein metadata from the first 10,000 local harvest nodes;
it does not publish the 8.9-million-node local store or research workspace.
Ask Atlas retains source-annotation lookup. Local Codex/TopK and Whisper services
are not deployed into this Worker. The reviewed /cluster and /api/evidence routes
remain available, and the chat retains its paper and evidence links.
Dense rendering uses a 1x pixel budget, GPU buffer reuse and lazy pointer indexing;
SVG labels and controls remain at native display resolution.

Active dense-graph version: 16284df3-d5e5-45d2-b7a8-9534270c5673 (100% traffic).
Verified release: deploy/cloudflare/dense-release.json
Rollback: uv run pywrangler versions deploy 7337a382-13f2-4951-a2b9-4a24bc9ecaa3@100% --yes
