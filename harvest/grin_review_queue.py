"""Extract Myers et al. 2023 published-variant functional-category lists.

Reads the locally retained PMC HTML, limits output to GluN2A/GluN2B entries in
one Discussion paragraph, and writes a separate human-review queue.
"""
from __future__ import annotations

import argparse
import json
import hashlib
import re
from html.parser import HTMLParser
from pathlib import Path

DEFAULT_SOURCE = Path("data/raw/harvest/grin_primary_pages/PMC10508039.html")
DEFAULT_DEMO = Path("data/curated/grin_functional_evidence.json")
DEFAULT_OUTPUT = Path("data/curated/grin_functional_review_queue.json")

# Exact author headings as they appear in the published paragraph.
AA3 = {"A":"Ala","R":"Arg","N":"Asn","D":"Asp","C":"Cys","Q":"Gln","E":"Glu","G":"Gly","H":"His","I":"Ile","L":"Leu","K":"Lys","M":"Met","F":"Phe","P":"Pro","S":"Ser","T":"Thr","W":"Trp","Y":"Tyr","V":"Val"}

CATEGORIES = [
    ("Likely GoF", "Likely GoF published variants include"),
    ("Possible GoF", "Possible GoF published variants include"),
    ("Likely LoF", "Likely LoF published variants include"),
    ("Possible LoF", "Possible LoF variants include"),
    ("Likely LoF (expression too low)", "classified variants with expression too low to measure responses"),
    ("No Effect or Indeterminant (grouped by source)", "Six published variants had"),
]

class ParagraphCollector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.paragraphs: list[str] = []
        self._in_p = False
        self._buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "p":
            self._in_p = True
            self._buf = []

    def handle_endtag(self, tag):
        if tag == "p" and self._in_p:
            self.paragraphs.append(" ".join("".join(self._buf).split()))
            self._in_p = False

    def handle_data(self, data):
        if self._in_p:
            self._buf.append(data)



class TableSectionRows(HTMLParser):
    """Collect text and detect images in selected PMC article table sections."""
    def __init__(self, section_ids):
        super().__init__(convert_charrefs=True)
        self.section_ids = set(section_ids)
        self.active = False
        self.target = None
        self.depth = 0
        self.rows_by_id = {section_id: [] for section_id in section_ids}
        self.row = []
        self.cell = ""
        self.cell_has_image = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "section" and attrs.get("id") in self.section_ids and not self.active:
            self.target = attrs["id"]
            self.active, self.depth = True, 1
        elif self.active:
            if tag == "section": self.depth += 1
            elif tag == "tr": self.row = []
            elif tag in ("td", "th"):
                self.cell = ""
                self.cell_has_image = False
            elif tag == "img":
                self.cell_has_image = True

    def handle_data(self, data):
        if self.active: self.cell += data

    def handle_endtag(self, tag):
        if not self.active: return
        if tag in ("td", "th"):
            self.row.append({"text": " ".join(self.cell.split()), "has_image": self.cell_has_image})
        elif tag == "tr" and any(cell["text"] or cell["has_image"] for cell in self.row):
            self.rows_by_id[self.target].append(self.row)
        elif tag == "section":
            self.depth -= 1
            if self.depth == 0:
                self.active, self.target = False, None


def extract_table_candidates(source_html: str, demo_data: dict) -> list[dict]:
    parser = TableSectionRows(("TB1", "TB6"))
    parser.feed(source_html)
    demo = {(v["gene"], v.get("reported_protein")) for v in demo_data.get("variants", [])}
    table6_calls = {}
    for row in parser.rows_by_id["TB6"]:
        if len(row) < 2:
            continue
        label = row[0]["text"].strip()
        match = re.fullmatch(r"([A-Z])([0-9]+)([A-Z])", label)
        if not match:
            continue
        final_cell = row[-1]
        call = final_cell["text"].strip() or None
        table6_calls[label] = {"call": call, "has_image": final_cell["has_image"]}

    candidates = []
    for row in parser.rows_by_id["TB1"][1:]:
        label = row[0]["text"].strip()
        match = re.fullmatch(r"([A-Z])([0-9]+)([A-Z])", label)
        if not match:
            continue
        ref, pos, alt = match.groups()
        protein_change = "p." + AA3[ref] + pos + AA3[alt]
        table6 = table6_calls.get(label, {"call": None, "has_image": False})
        available = table6["call"] is not None
        candidates.append({
            "gene": "GRIN2B",
            "source_protein_notation": "GluN2B-" + label,
            "protein_change": protein_change,
            "candidate_type": "newly_assayed_Table_1_variant",
            "author_category": table6["call"],
            "classification_status": "available_as_text_in_Table_6" if available else "unavailable_as_text; Table_6_classification_cell image-only or empty in retained HTML",
            "source_locator": "Myers et al. 2023, Table 1, row " + label + "; Table 6, row " + label + ", final-call cell.",
            "already_in_selected_demo": ("GRIN2B", protein_change) in demo,
            "cohort_admission": "not_automatically_admitted",
        })
    if len(candidates) != 14:
        raise ValueError(f"Expected 14 protein-variant rows in Table 1; found {len(candidates)}")
    return candidates


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def extract_paragraph(source_html: str) -> str:
    parser = ParagraphCollector()
    parser.feed(source_html)
    matches = [p for p in parser.paragraphs if "Likely GoF published variants include" in p and "classified variants with expression too low" in p]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one Myers published-variant category paragraph; found {len(matches)}")
    return matches[0]


def extract_entries(paragraph: str) -> list[dict]:
    entries = []
    for idx, (category, marker) in enumerate(CATEGORIES):
        start = paragraph.find(marker)
        if start < 0:
            raise ValueError(f"Missing category marker: {marker}")
        start += len(marker)
        later = [paragraph.find(m, start) for _, m in CATEGORIES[idx + 1:]]
        later = [x for x in later if x >= 0]
        end = min(later) if later else len(paragraph)
        text = paragraph[start:end]
        # Names are source forms such as GluN2B-C461F. Keep that exact token.
        for token in re.findall(r"GluN2[AB]-[A-Z][0-9]+[A-Z]", text):
            gene, protein = token.split("-", 1)
            entries.append({
                "gene": "GRIN2A" if gene == "GluN2A" else "GRIN2B",
                "source_protein_notation": token,
                "protein_change": "p." + AA3[protein[0]] + protein[1:-1] + AA3[protein[-1]],
                "author_category": category,
                "source_locator": "Myers et al. 2023, Discussion, paragraph beginning ‘To further illustrate the utility of this approach’; published-variant category list.",
            })
    # Preserve distinct class entries, but reject accidental duplicate source tokens.
    seen = set()
    for e in entries:
        key = (e["gene"], e["source_protein_notation"])
        if key in seen:
            raise ValueError(f"Duplicate variant in category paragraph: {key}")
        seen.add(key)
    return entries


def attach_demo_status(entries: list[dict], demo_data: dict) -> None:
    demo = {(v["gene"], v.get("reported_protein")) for v in demo_data.get("variants", [])}
    for entry in entries:
        entry["already_in_selected_demo"] = (entry["gene"], entry["protein_change"]) in demo
        entry["cohort_admission"] = "not_automatically_admitted"


def build(source_path=DEFAULT_SOURCE, demo_path=DEFAULT_DEMO) -> dict:
    paragraph = extract_paragraph(Path(source_path).read_text(encoding="utf-8"))
    entries = extract_entries(paragraph)
    demo_data = json.loads(Path(demo_path).read_text(encoding="utf-8"))
    attach_demo_status(entries, demo_data)
    source_html = Path(source_path).read_text(encoding="utf-8")
    table1_candidates = extract_table_candidates(source_html, demo_data)
    supplement_pdf = Path("data/raw/harvest/grin_supplements/supplemental_information_8-7-23_final6_ddad104.pdf")
    supplement_text = Path("data/raw/harvest/grin_supplements/myers2023-supplement.txt")
    # The prose calls this “six” but names four variants; record that source inconsistency.
    grouped = [e for e in entries if e["author_category"].startswith("No Effect or Indeterminant")]
    return {
        "schema_version": 1,
        "source": {
            "title": "Classification of missense variants in the N-methyl-D-aspartate receptor GRIN gene family as gain- or loss-of-function",
            "pmid": "37369021",
            "pmcid": "PMC10508039",
            "doi": "10.1093/hmg/ddad104",
            "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC10508039/",
            "local_source": str(source_path),
            "local_source_sha256": sha256(Path(source_path)),
            "supplement_pdf": str(supplement_pdf),
            "supplement_pdf_sha256": sha256(supplement_pdf),
            "supplement_text": str(supplement_text),
            "supplement_text_sha256": sha256(supplement_text),
            "supplement_crosschecks": {
                "table_s3": {"locator": "Supplemental Table S3", "discussion_listed_grin2a_b_matches": ["GluN2A-G483R", "GluN2A-A716T", "GluN2A-D731N", "GluN2B-E413G", "GluN2B-C461F", "GluN2B-S541G", "GluN2B-S541R", "GluN2B-R540H", "GluN2B-P553T"], "check": "All listed calls and relative-effect rows were checked against the Discussion categories; A639V is absent because it is from a later study."},
                "table_s4": {"locator": "Supplemental Table S4", "check": "Checked new Mg2+ IC50/current-response rows for WT and the listed GRIN2A/GRIN2B published variants; used as assay-data cross-reference, not as an independent category assignment."},
                "table_s5": {"locator": "Supplemental Table S5", "expression_limited_grin2a_b": ["GluN2A-R518H", "GluN2A-T531M", "GluN2A-A548P", "GluN2B-C436R", "GluN2B-A549V", "GluN2B-F550S", "GluN2B-L551S", "GluN2B-S555I", "GluN2B-P553L", "GluN2B-A636P"], "check": "All ten listed variants and their Likely LoF* calls checked."},
            },
            "locator": "Discussion, paragraph beginning ‘To further illustrate the utility of this approach’; published-variant category list.",
        },
        "scope": "Bounded source-linked review queue of GluN2A/GluN2B variants explicitly named in the published-variant classification paragraph. Not a complete catalog, reclassification, or cohort admission list.",
        "source_limitations": [
            "Category labels reproduce the paper's functional categories, not clinical pathogenicity labels; the supplementary Tables S3–S5 provide parameter-level cross-checks and identify expression-limited records.",
            "Newly assayed Table 1 GRIN2B variants are stored separately as candidates; Table 6 has readable text calls for some rows, while other final-call cells are unavailable in the retained HTML.",
            "The paragraph says six variants had No Effect or were Indeterminant but explicitly names only four GRIN2A/GRIN2B variants; this queue preserves the four named variants and does not invent the two missing names.",
            "Variants assigned Likely LoF because expression was too low are retained under their explicitly separate source statement; the source notes they were not fully characterized pharmacologically/biophysically.",
            "Entries are not automatically admitted to the selected functional cohort.",
        ],
        "counts": {
            "all_listed_grin2a_b_variants": len(entries),
            "category_counts": {cat: sum(e["author_category"] == cat for e in entries) for cat, _ in CATEGORIES},
            "no_effect_or_indeterminant_named_count": len(grouped),
            "new_table1_candidates": len(table1_candidates),
            "table1_candidates_classification_available_as_text": sum(x["classification_status"] == "available_as_text_in_Table_6" for x in table1_candidates),
            "table1_candidates_classification_unavailable_as_text": sum(x["classification_status"] != "available_as_text_in_Table_6" for x in table1_candidates),
        },
        "variants": entries,
        "newly_assayed_candidates": table1_candidates,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    ap.add_argument("--demo", type=Path, default=DEFAULT_DEMO)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = ap.parse_args()
    data = build(args.source, args.demo)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(data["counts"], indent=2))

if __name__ == "__main__":
    main()
