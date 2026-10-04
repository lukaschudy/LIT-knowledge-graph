# Missing-evidence proposals

Empty node and record searches offer **Propose an addition**. Explicit chat coverage gaps offer the same action. Unknown protein substitutions (including short aliases) cannot silently fall back to the selected variant's annotations.

The form retains the question and accepts an item name/type, description and optional published source URL. It stores a **pending_review** proposal in Cloudflare's SQLite-backed `ProposalInbox` Durable Object, named `review-inbox-v1`. The existing evidence graph and TopK index are not modified. Source links are stored as text, never automatically fetched. No emails or other messages are sent.

## Review and storage

The public API only accepts submissions and returns minimal receipt status by unguessable receipt ID. It never lists proposals or returns their descriptions. Signed-in account administrators can inspect the namespace and its SQL data in Cloudflare Durable Objects Data Studio. Select the `varentik-atlas` / `ProposalInbox` namespace and its populated object (the Worker addresses this singleton using `getByName("review-inbox-v1")`; the dashboard may display its opaque object ID instead). Inspect:

```sql
SELECT id, created_at, status, payload FROM proposals ORDER BY created_at DESC;
```

`payload` is JSON containing the original query, item type/name, description, URL and entry point. All of these fields are untrusted user input; review sources using the existing evidence and annotation workflow. There is no automatic approval or graph-promotion endpoint. A dedicated reviewer interface and promotion workflow are future work.

API validation enforces field lengths, a 12 KB request cap, HTTP(S) URLs without credentials, same-origin JSON submission, parameterized SQL, an inbox-wide cap of 120 new submissions/hour and server-owned pending status. UUID request IDs make identical retries idempotent; conflicting reuse returns 409. The hourly cap bounds anonymous traffic but is not an identity-based anti-abuse system.

## Local development and deployment

The legacy read-only `atlas.server` serves the form assets but does not accept submissions. Use the complete Cloudflare runtime for this feature:

```sh
.venv/bin/python scripts/build_cloudflare.py
cd deploy/cloudflare
./.venv/bin/pywrangler dev --port 8788
```

Local Durable Object storage persists under the ignored `.wrangler` directory. Production storage belongs to the deployed namespace and survives code deployments. Do not delete the Durable Object class/namespace or apply a deletion migration while proposals need retention.

Build with `scripts/build_cloudflare.py --committed-assets` when another task is changing frontend files concurrently; this publishes the committed asset snapshot. Initial namespace creation requires `pywrangler deploy`; subsequent code-only releases use `versions upload` and `versions deploy`. Existing Cloudflare route permissions may cause the deploy command's route update to fail after a successful Worker upload; verify the actual deployed version and the unchanged domain before reporting completion.
