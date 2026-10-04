"""Local article snapshots with table geometry and explicit coverage gaps.

No downloads, scientific labels, or inferred independent-study assignments.
"""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass, field
from hashlib import sha256
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
from urllib.parse import urljoin, urlsplit

from .contracts import VERSION, digest, source_index, validate_reference
from .prepare import file_sha

PARSER_VERSION = "article-snapshot-v1"
VOID = set("area base br col embed hr img input link meta param source track wbr".split())


@dataclass
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    parent: object = None
    path: str = ""

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def parents(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent

    def text(self):
        if self.tag in {"script", "style", "noscript"}:
            return ""
        if self.tag == "br":
            return " "
        return "".join(c.text() if isinstance(c, Node) else c for c in self.children)


class Tree(HTMLParser):
    """Parse the explicit, well-formed article markup in our saved PMC pages."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.repairs = []

    def handle_starttag(self, tag, attrs):
        parent = self.stack[-1]
        count = sum(isinstance(c, Node) and c.tag == tag for c in parent.children) + 1
        node = Node(tag, dict(attrs), [], parent, parent.path + f"/{tag}[{count}]")
        parent.children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                if i != len(self.stack) - 1:
                    self.repairs.append({"closing_tag": tag, "unclosed_tags": [n.tag for n in self.stack[i+1:]],
                                         "path": self.stack[i].path})
                self.stack = self.stack[:i]
                return

    def handle_data(self, text):
        self.stack[-1].children.append(text)


def http_url(base, value):
    resolved = urljoin(base, value)
    return resolved if urlsplit(resolved).scheme in {"http", "https"} else None


def images(node, base):
    return [{"url": http_url(base, n.attrs.get("src", "")), "alt": n.attrs.get("alt", ""),
             "path": n.path} for n in node.walk() if n.tag == "img"]


def section(node):
    parts = []
    for ancestor in reversed(list(node.parents())):
        if ancestor.tag in {"section", "article"}:
            title = next((c for c in ancestor.children if isinstance(c, Node) and c.tag in {"h1", "h2", "h3", "h4"}), None)
            if title:
                parts.append(" ".join(title.text().split()))
    return " / ".join(parts)


def parse_article(html, document_id, base_url):
    tree = Tree()
    tree.feed(html)
    tree.close()
    articles = [n for n in tree.root.walk() if n.tag == "article"]
    if len(articles) != 1:
        raise ValueError(f"{document_id}: require exactly one article, found {len(articles)}")
    article = articles[0]
    units, metadata, tables = [], {}, []
    nodes = list(article.walk())

    def add(node, kind, *, locator=None, extra=None):
        text = " ".join(node.text().split())
        if not text:
            return None
        uid = document_id + ":html:" + sha256(node.path.encode()).hexdigest()[:20]
        units.append({"unit_id": uid, "document_id": document_id, "kind": kind,
                      "locator": locator or "html:" + node.path, "text": text})
        metadata[uid] = {"section": section(node), "images": images(node, base_url),
                         "source_element_id": node.attrs.get("id"), **(extra or {})}
        return uid

    for table_number, table in enumerate((n for n in nodes if n.tag == "table"), 1):
        if any(p.tag == "table" for p in table.parents()):
            raise ValueError("Nested tables need explicit parser support")
        table_id = document_id + f":table:{table_number}"
        rows = [n for n in table.walk() if n.tag == "tr"]
        occupied = set()
        cells = []
        for row_number, row in enumerate(rows, 1):
            column = 1
            for cell in (n for n in row.children if isinstance(n, Node) and n.tag in {"th", "td"}):
                while (row_number, column) in occupied:
                    column += 1
                height, width = int(cell.attrs.get("rowspan", "1")), int(cell.attrs.get("colspan", "1"))
                if not (1 <= height <= len(rows) and 1 <= width <= 100 and row_number + height - 1 <= len(rows)):
                    raise ValueError(f"Invalid table span at {cell.path}")
                slots = {(r, c) for r in range(row_number, row_number + height) for c in range(column, column + width)}
                if occupied & slots:
                    raise ValueError(f"Overlapping cells at {cell.path}")
                occupied |= slots
                shape = {"table_id": table_id, "row": row_number, "column": column, "rowspan": height,
                         "colspan": width, "header": cell.tag == "th"}
                locator = f"html:{cell.path}; table {table_number}; row {row_number}; column {column}; rowspan {height}; colspan {width}"
                uid = add(cell, "table_cell", locator=locator, extra=shape)
                cells.append({**shape, "unit_id": uid, "text": " ".join(cell.text().split()),
                              "images": images(cell, base_url), "locator": locator})
                column += width
        parent = table.parent
        # PMC places captions/footnotes outside the actual <table> element.
        wrapper = next((n for n in table.parents() if n.attrs.get("class", "").split()
                        and any(c in n.attrs.get("class", "").split() for c in ("tw", "table-wrap"))), parent)
        tables.append({"table_id": table_id, "number": table_number, "path": table.path,
                       "section": section(table), "wrapper_path": wrapper.path,
                       "role": "equation" if "disp-formula" in table.attrs.get("class", "") else "table",
                       "row_count": len(rows), "column_count": max((c for _, c in occupied), default=0), "cells": cells})

    selected = []
    for node in nodes:
        if any(p.tag == "table" for p in node.parents()) or node.tag in {"table", "td", "th"}:
            continue
        classes = node.attrs.get("class", "").split()
        is_caption = "caption" in classes
        is_footnote = "tw-foot" in classes or node.tag == "footer"
        if not (node.tag in {"p", "h1", "h2", "h3", "h4", "h5", "h6"} or is_caption or is_footnote
                or node.tag == "li" and not any(n.tag == "p" for n in node.walk())):
            continue
        if any(p.path in selected for p in node.parents()):
            continue
        ancestors = [node, *node.parents()]
        kind = "footnote" if is_footnote else "caption" if is_caption else "methods" if "method" in section(node).lower() else "paragraph"
        role = "heading" if node.tag.startswith("h") and len(node.tag) == 2 else "text"
        if any("ref-list" in p.attrs.get("class", "") or "ref-list" in p.attrs.get("id", "") for p in ancestors):
            role = "bibliography"
        add(node, kind, extra={"role": role})
        selected.append(node.path)
    units.sort(key=lambda u: u["unit_id"])
    if len({u["unit_id"] for u in units}) != len(units):
        raise ValueError("Duplicate source unit")
    all_images = images(article, base_url)
    supplement_links = []
    for n in nodes:
        if n.tag == "a" and n.attrs.get("href"):
            href = n.attrs["href"]
            if "/bin/" in href or "supplement" in href.lower():
                url = http_url(base_url, href)
                if url:
                    supplement_links.append({"url": url, "text": " ".join(n.text().split()), "path": n.path})
    return units, {"document_id": document_id, "parser_version": PARSER_VERSION, "unit_metadata": metadata,
                   "tables": tables, "images": all_images, "supplement_links": supplement_links,
                   "article_tree_repairs": [r for r in tree.repairs if r["path"].startswith(article.path)],
                   "counts": {"units": len(units), "by_kind": dict(Counter(u["kind"] for u in units)),
                              "tables": len(tables), "cells": sum(len(t["cells"]) for t in tables),
                              "empty_cells": sum(c["unit_id"] is None for t in tables for c in t["cells"]),
                              "image_bearing_cells": sum(bool(c["images"]) for t in tables for c in t["cells"]),
                              "images": len(all_images)},
                   "coverage": "partial_pending_visual_and_supplement_audit"}


def write_json(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def build(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("Output directory exists; snapshots are immutable")
    manifest = json.loads((root / "data/benchmarks/grin-v1/development-manifest.json").read_text())
    original_manifest_sha = digest(manifest)
    # Source metadata only; no existing scientific labels enter the reviewer package.
    inventory = json.loads((root / "data/benchmarks/grin-v1/candidate-inventory.json").read_text())
    candidates = {d["document_id"]: d for d in inventory["documents"]}
    harvest = json.loads((root / "data/harvest-manifests/grin_primary_pages.json").read_text())
    sources = {"schema_version": VERSION, "units": []}
    ledger = {"schema_version": "grin-source-ledger-v1", "parser_version": PARSER_VERSION, "documents": [],
              "limitations": ["No visual transcription or independent annotation performed.",
                              "Linked images are recorded but not downloaded or numerically interpreted.",
                              "Supplement coverage is limited to already acquired files; missing supplements remain gaps.",
                              "HTML text is whitespace-normalized; offsets address source units, not original HTML."]}
    originals = []
    for doc in manifest["documents"]:
        doc_id = doc["document_id"]
        artifact = harvest["artifacts"][doc_id + ".html"]
        path = root / artifact["path"]
        if file_sha(path) != artifact["sha256"]:
            raise ValueError(f"Original artifact hash mismatch: {doc_id}")
        units, details = parse_article(path.read_text(encoding="utf-8"), doc_id, candidates[doc_id]["url"])
        originals.append((path, doc_id + ".html"))
        details.update(title=candidates[doc_id]["title"], url=candidates[doc_id]["url"],
                       original={"path": artifact["path"], "sha256": artifact["sha256"], "license": artifact["license"]},
                       supplemental_files=[])
        if doc_id == "PMC10508039":
            supplement = json.loads((root / "data/harvest-manifests/grin_supplements.json").read_text())
            derived = {Path(d["path"]).suffix: d for d in supplement["derived_files"]}
            for info in derived.values():
                source = root / info["path"]
                if file_sha(source) != info["sha256"]:
                    raise ValueError("Supplement snapshot mismatch")
                originals.append((source, source.name))
                details["supplemental_files"].append({**info, "review_status": "layout_and_images_need_review"})
            pdf_path = root / derived[".pdf"]["path"]
            if not pdf_path.read_bytes().startswith(b"%PDF"):
                raise ValueError("Supplement is not a PDF")
            pages = (root / derived[".txt"]["path"]).read_text().split("\f")
            for index, page in enumerate(pages, 1):
                if not page.strip():
                    continue
                uid = doc_id + f":supplement:page:{index}"
                units.append({"unit_id": uid, "document_id": doc_id, "kind": "paragraph",
                              "locator": f"supplement:{pdf_path.name}; page {index}; pdftotext-layout", "text": page})
                details["unit_metadata"][uid] = {"section": "Supplement", "role": "layout_text_unreviewed", "images": []}
            details["counts"]["supplement_pages"] = sum(u["unit_id"].startswith(doc_id + ":supplement:") for u in units)
        else:
            details["counts"]["supplement_pages"] = 0
        details["counts"]["units"] = len(units)
        details["counts"]["by_kind"] = dict(Counter(u["kind"] for u in units))
        doc["source_sha256"] = digest(sorted(units, key=lambda r: r["unit_id"]))
        sources["units"].extend(units)
        ledger["documents"].append(details)
    manifest["scope"] = "Seven previously curated development papers with normalized source snapshots; visual/supplement coverage, study grouping and independent annotations remain pending."
    reference = {"schema_version": VERSION, "manifest_sha256": digest(manifest), "split": "development",
                 "documents": [{"document_id": d["document_id"], "coverage": "partial",
                                "review": {"annotators": [], "adjudicator": None, "expert_reviewed": False},
                                "observations": [], "decisions": []} for d in manifest["documents"]]}
    source_index(manifest, sources)
    validate_reference(manifest, sources, reference)
    output.mkdir(parents=True)
    (output / "originals").mkdir()
    for source, name in originals:
        shutil.copyfile(source, output / "originals" / name)
    for name, value in (("manifest.json", manifest), ("sources.json", sources), ("source-ledger.json", ledger),
                        ("blank-reference.json", reference)):
        write_json(output / name, value)
    receipt = {"schema_version": "grin-snapshot-receipt-v1", "parser_version": PARSER_VERSION,
               "seed_manifest_sha256": original_manifest_sha, "manifest_sha256": digest(manifest),
               "sources_sha256": digest(sources), "ledger_sha256": digest(ledger),
               "files": {name: file_sha(output / name) for name in ("manifest.json", "sources.json", "source-ledger.json", "blank-reference.json")},
               "documents": [{"document_id": d["document_id"], "source_sha256": next(m["source_sha256"] for m in manifest["documents"] if m["document_id"] == d["document_id"]),
                              "counts": d["counts"], "coverage": d["coverage"], "article_tree_repairs": len(d["article_tree_repairs"])} for d in ledger["documents"]],
               "annotation_status": "blank_unassigned_not_independently_reviewed", "held_out_documents": 0}
    write_json(output / "receipt.json", receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args.root, args.output)
    print(json.dumps({"documents": len(result["documents"]), "source_units": sum(d["counts"]["units"] for d in result["documents"]),
                      "annotation_status": result["annotation_status"], "output": str(args.output)}))


if __name__ == "__main__":
    main()
