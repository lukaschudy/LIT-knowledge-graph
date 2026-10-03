"""TopK transport and evidence-preserving reciprocal-rank hybrid retrieval."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import time

from .passages import canonical, file_sha, gene_mentions, protein_mentions, read_rows

DEFAULT_REGION = "aws-us-east-1-elastica"
FIELDS = ("_id", "title", "content", "source_id", "url", "locator", "kind", "license",
          "genes", "proteins", "node_ids", "claim_id", "evidence_id", "effect",
          "cohort_tier", "review_status", "identity_scope", "stance", "context_json", "snapshot_id")


def settings(env_file=None):
    """Read only recognized literal assignments; never execute a secret file."""
    values = {}
    if env_file:
        for line in Path(env_file).read_text().splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            name, sep, value = line.partition("=")
            name = name.strip().removeprefix("export ")
            if sep and name in {"TOPK_API_KEY", "TOPK_REGION", "TOPK_COLLECTION"}:
                values[name] = value.strip().strip("\"'")
    values.update({k: v for k, v in os.environ.items() if k.startswith("TOPK_") and v})
    if not values.get("TOPK_API_KEY"):
        raise ValueError("TOPK_API_KEY is missing; configure an ignored local .env or environment")
    return values


def client_from_settings(values):
    from topk_sdk import Client
    return Client(api_key=values["TOPK_API_KEY"], region=values.get("TOPK_REGION") or DEFAULT_REGION)


def schema():
    from topk_sdk.schema import text, semantic_index, keyword_index, list as list_field
    fields = {name: text() for name in FIELDS if name != "_id"}
    fields["content"] = text().required().index(semantic_index())
    fields["title"] = text().required().index(keyword_index())
    for name in ("genes", "proteins", "node_ids"):
        fields[name] = list_field("text")
    return fields


def batches(rows, max_docs=100, max_bytes=1000000):
    batch, size = [], 0
    for row in rows:
        length = len(canonical(row).encode())
        if length > 64000:
            raise ValueError("Oversized search document")
        if batch and (len(batch) >= max_docs or size + length > max_bytes):
            yield batch
            batch, size = [], 0
        batch.append(row)
        size += length
    if batch:
        yield batch


def wire_documents(rows):
    from topk_sdk.data import string_list
    return [{k: string_list(v) if isinstance(v, list) else v for k, v in row.items()} for row in rows]


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def ingest(client, collection, export_path, state_path, region, *, create=False, progress=None):
    """Resume only an identical export/target. Acknowledgements precede checkpoints."""
    export_path, state_path = Path(export_path), Path(state_path)
    manifest = json.loads(export_path.with_suffix(export_path.suffix + ".manifest.json").read_text())
    if file_sha(export_path) != manifest["export_sha256"]:
        raise ValueError("Export checksum does not match manifest")
    target = {"collection": collection, "region": region, "export_sha256": manifest["export_sha256"],
              "snapshot_id": manifest["snapshot_id"], "batch_version": 1}
    state = {**target, "acknowledged_documents": 0, "acknowledged_batches": 0, "status": "uploading"}
    if state_path.exists():
        state = json.loads(state_path.read_text())
        if any(state.get(k) != v for k, v in target.items()):
            raise ValueError("Checkpoint belongs to a different export or target; use a new checkpoint")
    state["bundle_sha256"] = manifest["input_sha256"]["data/curated/grin_atlas_bundle.json"]
    if create:
        # Never mask a permission/schema error as 'already exists'.
        from topk_sdk.error import CollectionAlreadyExistsError
        try:
            client.collections().create(collection, schema=schema())
        except CollectionAlreadyExistsError:
            pass
    remote = client.collection(collection)
    for index, batch in enumerate(batches(read_rows(export_path))):
        if index < state["acknowledged_batches"]:
            continue
        lsn = remote.upsert(wire_documents(batch))
        state.update(acknowledged_batches=index + 1,
                     acknowledged_documents=state["acknowledged_documents"] + len(batch),
                     last_lsn=lsn, status="uploading")
        save_json(state_path, state)
        if progress:
            progress({"uploaded": state["acknowledged_documents"], "total": manifest["documents"]})
    if state["acknowledged_documents"] != manifest["documents"]:
        raise ValueError("Acknowledged count does not match manifest")
    state["status"] = "uploaded_not_verified"
    save_json(state_path, state)
    # Verify every identifier and its content, not just the global collection count.
    verified = 0
    for batch in batches(read_rows(export_path)):
        found = remote.get([r["_id"] for r in batch], lsn=state.get("last_lsn"))
        for expected in batch:
            actual = found.get(expected["_id"])
            if actual is None or any(actual.get(k) != v for k, v in expected.items() if k != "_id"):
                raise ValueError("TopK read-back differs from local export")
            verified += 1
    state.update(status="verified", verified_documents=verified)
    save_json(state_path, state)
    return state


def resolve_filters(query, gene=None, protein=None):
    genes = gene_mentions(query)
    proteins = protein_mentions(query)
    if gene is not None:
        gene = gene.upper()
        if gene not in {"GRIN2A", "GRIN2B"}:
            raise ValueError("Pilot gene filter must be GRIN2A or GRIN2B")
    elif len(genes) == 1:
        gene = genes[0]
    if protein is not None:
        parsed = protein_mentions(protein)
        if len(parsed) != 1:
            raise ValueError("Supply one protein substitution, e.g. S541R or p.Ser541Arg")
        protein = parsed[0]
    elif len(proteins) == 1 and gene:
        protein = proteins[0]
    if protein and not gene:
        raise ValueError("A variant filter requires a gene; protein substitutions alone are ambiguous")
    return gene, protein


def make_query(query, snapshot, mode, limit, *, gene=None, protein=None, kind=None):
    from topk_sdk.query import select, field, fn, match
    filters = field("snapshot_id") == snapshot
    if gene:
        filters = filters & field("genes").contains(gene)
    if protein:
        filters = filters & field("proteins").contains(protein)
    if kind:
        filters = filters & (field("kind") == kind)
    if mode == "semantic":
        score = fn.semantic_similarity("content", query)
    elif mode == "keyword":
        score = fn.bm25_score()
    else:
        raise ValueError("Unknown retrieval channel")
    result = select(*FIELDS, retrieval_score=score).filter(filters)
    if mode == "keyword":
        # SDK text expressions and logical expressions are different types.
        result = result.filter(match(query))
    return result.sort(field("retrieval_score"), asc=False).limit(limit)


def fuse(rankings, k=10):
    """RRF avoids mixing uncalibrated BM25 and semantic numerical scales."""
    hits = {}
    for channel, rows in rankings.items():
        seen = set()
        for rank, row in enumerate(rows, 1):
            key = row["_id"]
            if key in seen:
                continue
            seen.add(key)
            if key not in hits:
                hits[key] = {**row, "rrf_score": 0.0, "channel_ranks": {}}
            hits[key]["rrf_score"] += 1 / (60 + rank)
            hits[key]["channel_ranks"][channel] = rank
    return sorted(hits.values(), key=lambda r: (-r["rrf_score"], r["_id"]))[:k]


def search(client, collection, query, snapshot, *, k=10, mode="hybrid", gene=None,
           protein=None, kind=None, lsn=None):
    if not query.strip() or not 1 <= k <= 100:
        raise ValueError("Search needs nonempty text and 1 <= k <= 100")
    if mode not in {"hybrid", "semantic", "keyword"}:
        raise ValueError("Mode must be hybrid, semantic or keyword")
    gene, protein = resolve_filters(query, gene, protein)
    started = time.monotonic()
    channels = ["semantic", "keyword"] if mode == "hybrid" else [mode]
    def retrieve(channel):
        q = make_query(query, snapshot, channel, max(50, k), gene=gene, protein=protein, kind=kind)
        return client.collection(collection).query(q, lsn=lsn)
    with ThreadPoolExecutor(max_workers=len(channels)) as pool:
        results = dict(zip(channels, pool.map(retrieve, channels)))
    hits = fuse(results, k) if mode == "hybrid" else results[mode][:k]
    return {"query": query, "mode": mode, "snapshot_id": snapshot,
            "filters": {"gene": gene, "protein": protein, "kind": kind},
            "latency_ms": round((time.monotonic() - started) * 1000, 1),
            "hits": hits, "graph_write_performed": False}


def graph_connections(hits, bundle):
    """Return existing qualified claims only, anchored to retrieved evidence IDs."""
    claims = {c["id"]: c for c in bundle["claims"]}
    evidence = {e["id"]: e for e in bundle["evidence"]}
    result = {}
    for hit in hits:
        e = evidence.get(hit.get("evidence_id"))
        if hit.get("kind") != "curated_evidence" or not e or e["claim_id"] != hit.get("claim_id"):
            continue
        claim = claims[e["claim_id"]]
        if claim["id"] not in result:
            result[claim["id"]] = {"claim": claim, "matched_evidence": [],
                                  "status": "existing_claim; scientific review status retained"}
        result[claim["id"]]["matched_evidence"].append(e)
    return list(result.values())


def checked_bundle(path, state):
    """Sequential claim/evidence IDs are valid only within the same bundle revision."""
    if not state.get("bundle_sha256") or file_sha(path) != state["bundle_sha256"]:
        raise ValueError("Graph bundle differs from the indexed revision; re-export before linking claims")
    return json.loads(Path(path).read_text())
