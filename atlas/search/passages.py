"""Deterministic, streaming GRIN passage export from the audited local harvest."""
from __future__ import annotations

from collections import Counter
import gzip
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

VERSION = "grin-passages-v1"
AA = dict(zip(
    "Ala Arg Asn Asp Cys Gln Glu Gly His Ile Leu Lys Met Phe Pro Ser Thr Trp Tyr Val".split(),
    "ARNDCQEGHILKMFPSTWYV"))
PROTEIN = re.compile(r"(?<![A-Za-z0-9])(?:p\.)?(" + "|".join(AA) + r")(\d+)(" + "|".join(AA) + r")(?![A-Za-z0-9])", re.I)
SHORT = re.compile(r"(?<![A-Za-z0-9])(?:p\.)?([ARNDCQEGHILKMFPSTWYV])(\d+)([ARNDCQEGHILKMFPSTWYV])(?![A-Za-z0-9])", re.I)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def file_sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read_rows(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            yield json.loads(line)


def protein_mentions(text):
    found = {a.upper() + n + b.upper() for a, n, b in SHORT.findall(text)}
    found.update(AA[a.title()] + n + AA[b.title()] for a, n, b in PROTEIN.findall(text))
    return sorted(found)


def gene_mentions(text):
    return sorted({"GRIN2" + m.upper() for m in re.findall(r"\b(?:GRIN2|GluN2)([AB])\b", text, re.I)})


def chunks(text, maximum=3600, overlap=400):
    """Character offsets refer to whitespace-normalized source unit text."""
    if not 0 <= overlap < maximum:
        raise ValueError("Require 0 <= overlap < maximum")
    text = " ".join(text.split())
    start = 0
    while start < len(text):
        end = min(start + maximum, len(text))
        if end < len(text):
            boundary = text.rfind(" ", start + maximum // 2, end)
            if boundary > start:
                end = boundary
        yield start, end, text[start:end]
        if end == len(text):
            break
        start = max(start + 1, end - overlap)
        if start and text[start - 1] != " ":
            boundary = text.find(" ", start, end)
            if boundary >= 0:
                start = boundary + 1


def xml_units(xml):
    """Keep paragraph/section locators; table text is explicitly uninterpreted."""
    root = ET.fromstring(xml)
    article = root if root.tag == "article" else root.find("article")
    if article is None or article.find("body") is None:
        raise ValueError("Full-text record has no article body")

    def walk(el, path, section):
        title = el.find("title")
        if title is not None:
            section = " / ".join(filter(None, [section, " ".join(title.itertext())]))
        if el.tag in {"p", "table-wrap", "fig"}:
            text = " ".join(" ".join(el.itertext()).split())
            if text:
                kind = "table_text_uninterpreted" if el.tag == "table-wrap" else "article_text"
                yield path + ("#" + el.attrib["id"] if el.get("id") else ""), section, text, kind
            return
        counts = Counter()
        for child in el:
            counts[child.tag] += 1
            if child.tag not in {"title", "ref-list"}:
                yield from walk(child, f"{path}/{child.tag}[{counts[child.tag]}]", section)

    for i, abstract in enumerate(article.findall("front/article-meta/abstract"), 1):
        yield from walk(abstract, f"article/front/article-meta/abstract[{i}]", "Abstract")
    yield from walk(article.find("body"), "article/body", "")


def base_document(*, source_id, title, url, locator, content, kind, license, **extra):
    return {
        "source_id": source_id, "title": title, "url": url, "locator": locator,
        "content": content, "kind": kind, "license": license,
        "genes": gene_mentions(content), "proteins": protein_mentions(content),
        "node_ids": [], "claim_id": "", "evidence_id": "", "effect": "unknown",
        "cohort_tier": "unclassified", "review_status": "unreviewed",
        "identity_scope": "text mention; gene/protein co-occurrence does not resolve an allele",
        "stance": "unclassified", "context_json": "{}", **extra,
    }


def bundle_documents(bundle):
    nodes = {n["id"]: n for n in bundle["nodes"]}
    sources = {s["id"]: s for s in bundle["sources"]}
    claims = {c["id"]: c for c in bundle["claims"]}
    # Evidence cards contain the source paraphrase and qualified claim context.
    # Do not copy a variant's overall classification onto unrelated evidence.
    for e in bundle["evidence"]:
        c, s = claims[e["claim_id"]], sources[e["source_id"]]
        endpoints = [nodes[c["subject"]], nodes[c["object"]]]
        labels = " → ".join([endpoints[0]["label"], c["predicate"], endpoints[1]["label"]])
        aliases = sorted({a for n in endpoints for a in n["aliases"]})
        text = labels + "\n" + e["excerpt"] + "\nContext: " + canonical(c["context"])
        proteins = protein_mentions(" ".join(n["label"] for n in endpoints))
        text += "\nSearch aliases: " + " ".join(aliases + proteins)
        genes = sorted({n["properties"]["gene"] for n in endpoints if n["properties"].get("gene")}
                       | {n["label"] for n in endpoints if n["type"] == "Gene"})
        yield base_document(
            source_id=s["id"], title=s["title"], url=s["url"], locator=e["locator"],
            content=text, kind="curated_evidence", license=s["license"],
            genes=genes or gene_mentions(text), proteins=proteins,
            node_ids=[n["id"] for n in endpoints], claim_id=c["id"], evidence_id=e["id"],
            effect=c["context"].get("effect", "unknown"),
            cohort_tier=c["context"].get("cohort_tier", "unclassified"),
            review_status=e["review_status"], stance=e["stance"],
            context_json=canonical(c["context"]),
            identity_scope="curated graph entity; protein-level variant identity unless a transcript is explicitly supplied",
        )


def article_documents(row):
    license = row["license"].lower().strip()
    if license not in {"cc by", "cc by-nc", "cc by-nc-sa", "cc by-sa", "cc0"}:
        raise ValueError("Unexpected rights status in licensed full-text input")
    pmcid = row["pmcid"]
    if not re.fullmatch(r"PMC\d+", pmcid):
        raise ValueError("Invalid PMCID")
    if "jats_xml" in row:
        units = xml_units(row["jats_xml"])
    else:
        units = [("body_text", "HTML body (includes uncurated page text)", row["body_text"], "article_text")]
    for locator, section, text, kind in units:
        for start, end, part in chunks(text):
            content = row["title"] + "\n" + section + "\n" + part
            yield base_document(
                source_id=pmcid, title=row["title"],
                url=f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/",
                locator=f"{locator}; normalized characters {start}:{end}",
                content=content, kind=kind, license=row["license"],
                # Tags refer to this passage, not every variant in the paper.
                genes=gene_mentions(part), proteins=protein_mentions(part),
                section=section, pmcid=pmcid, pmids=row.get("pmids", []),
            )


def export(root, output, *, fulltext=True):
    root, output = Path(root).resolve(), Path(output)
    bundle_path = root / "data/curated/grin_atlas_bundle.json"
    paths = [bundle_path]
    if fulltext:
        paths += [root / "data/processed/harvest/pmc_grin_oa" / name for name in
                  ("grin_licensed_full_text.jsonl.gz", "grin_html_full_text.jsonl.gz")]
    inputs = {str(p.relative_to(root)): file_sha(p) for p in paths}
    snapshot = digest(canonical({"version": VERSION, "inputs": inputs}))[:24]
    bundle = json.loads(bundle_path.read_text())
    from atlas.model import require_valid_bundle
    require_valid_bundle(bundle)
    counts, sources, licenses = Counter(), set(), Counter()
    seen, total_bytes, max_doc_bytes = set(), 0, 0
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")

    def documents():
        yield from bundle_documents(bundle)
        for path in paths[1:]:
            for row in read_rows(path):
                yield from article_documents(row)

    with temporary.open("wb") as raw:
        # Reproducible gzip (no timestamp or filename in its header).
        with gzip.GzipFile(fileobj=raw, mode="wb", filename="", mtime=0, compresslevel=6) as f:
            for doc in documents():
                doc["snapshot_id"] = snapshot
                doc["export_version"] = VERSION
                doc["_id"] = digest(canonical(doc))
                if doc["_id"] in seen:
                    continue
                seen.add(doc["_id"])
                data = (canonical(doc) + "\n").encode()
                if len(data) > 64000:
                    raise ValueError("Document exceeds conservative 64KB transport limit")
                f.write(data)
                total_bytes += len(data)
                max_doc_bytes = max(max_doc_bytes, len(data))
                counts[doc["kind"]] += 1
                licenses[doc["license"]] += 1
                sources.add(doc["source_id"])
    temporary.replace(output)
    manifest = {
        "version": VERSION, "snapshot_id": snapshot, "input_sha256": inputs,
        "documents": sum(counts.values()), "by_kind": dict(counts),
        "distinct_sources": len(sources), "licenses": dict(licenses),
        "uncompressed_bytes": total_bytes, "max_document_bytes": max_doc_bytes,
        "export_sha256": file_sha(output), "export_bytes": output.stat().st_size,
        "live_topk_status": "not_verified_by_export",
        "scope": "GRIN curated evidence and locally harvested licensed full texts" if fulltext else "GRIN curated evidence",
        "limitations": ["Full text is unreviewed discovery evidence, not extracted graph claims.",
                         "Text co-occurrence does not resolve gene/variant or transcript identity.",
                         "Tables retain source locators but layout and images are not interpreted.",
                         "NC licenses limit reuse; retain source attribution and license per passage."],
    }
    output.with_suffix(output.suffix + ".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
