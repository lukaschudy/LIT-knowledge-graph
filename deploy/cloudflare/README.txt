Atlas on Cloudflare

Build the current frontend and the reviewed real GRIN cluster:
  python3 scripts/build_cloudflare.py
  python3 scripts/verify_cloudflare_build.py

Run Cloudflare locally (install uv and Node.js first):
  cd deploy/cloudflare
  uv run pywrangler dev --port 8788

Deploy application updates without changing domain routes:
  # From repository root; --pywrangler may name its installed absolute path.
  python3 scripts/upload_cloudflare.py --message "Describe the update"
  cd deploy/cloudflare
  uv run pywrangler versions deploy <returned-version-id>@100% --yes

For first-time setup with route/DNS permissions:
  uv run pywrangler deploy

The build verifies the committed annotation receipt, then publishes the real
35-node graph and all 340 reviewed observation records / 53 annotation claims.
It refuses synthetic fixtures. A failed build preserves the previous complete
build unchanged. A successful build replaces the entire allowlisted output tree,
removing obsolete assets/modules that could otherwise leak into an upload.
The graph's effect assertions and variant summaries use the reviewed reference;
older scalar functional summaries are removed from the derived deployment.
The build copies only allowlisted web assets, the shared read-only API, graph
reasoner, annotation lookup, reviewed metadata and bounded source spans. It does
not publish local SQLite files, complete harvested papers, environment variables,
or arbitrary repository contents. A clean checkout uses the committed, bounded
public excerpt snapshot sealed by cloudflare_public_data_receipt.json. These
545 spans are the same table cells and short supplement rows already published.
When the ignored frozen source snapshot exists locally, the builder verifies
its digest and re-extracts the spans to require an exact match as well.

The manifest records SHA-256 hashes of generated files and build inputs. Verify
immediately before upload: it rejects changed inputs, changed output, and extra
files. Concurrent edits detected during packaging abort without replacing the
previous build. The build, verifier and upload wrapper share a POSIX release
lock so a concurrent build cannot replace files while uploading. Use the upload
wrapper instead of plain versions upload; invoking Wrangler directly bypasses
that guard. The wrapper checks the installed pywrangler version, synchronizes
its Python dependencies, then verifies both the build and the exact vendor tree.
The vendor check uses the SDK wheel SHA-256 pinned in pylock.toml, not the
installed RECORD file: extra files, changed libraries, forged RECORD hashes,
symlinks and stale sync markers prevent upload. The audited versions are
workers-py 1.17.6 and workers-runtime-sdk 1.9.2; dependency upgrades require
reviewing that packaging contract. Use --wheel /absolute/path/to/pinned.whl on
the upload wrapper to verify offline; it still checks the pinned hash.
This lock covers packaging only, never production inbox data.
Do not edit generated files to work around a failure; fix the
source and rebuild. --committed-assets uses HEAD for frontend assets only; the
manifest records that choice and the backend/data still use the working tree.

To refresh curated data, first rerun and review the annotation/source audit.
The cluster/reference receipt, public excerpts, dense snapshot and public data
receipt must describe the same reviewed revision. Never simply update hashes
for an unexplained changed data file. The normal build is read-only with respect
to those inputs and does not silently regenerate or bless data receipts.
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

Active dense-graph version: ab5a8ebd-8a82-48d4-ad4c-36f767beb089 (100% traffic).
Verified release: deploy/cloudflare/dense-release.json
Rollback: uv run pywrangler versions deploy f5d059b4-8b9a-4748-bffa-8d720294e332@100% --yes

Nodes keep fixed world positions during pointer gestures; dragging orbits the camera.
The current theme uses a white background, dark lotus-green branding and the original
multicolour node palette. Node positions remain fixed while dragging orbits the camera.
The existing ProposalInbox binding and private proposal receipt workflow are preserved.

Reliability release verification: deploy/cloudflare/reliability-release.json
Audit findings and remaining limits: docs/research/reliability-review-2026-10-04.md
