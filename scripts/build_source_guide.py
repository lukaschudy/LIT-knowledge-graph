#!/usr/bin/env python3
"""Assemble the single-file guide and audit PDF-source coverage (no network)."""
import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build():
    catalog = json.loads((ROOT / 'data/source/catalog.json').read_text())
    ids = [row['id'] for row in catalog]
    if ids != [f'S{i:02}' for i in range(1, 22)]:
        raise ValueError('Catalog must include S01–S21 exactly once in PDF-review order')
    review_ids = re.findall(r'^\| (S\d+) \|', (ROOT / 'docs/pdf-review.md').read_text(), re.M)
    if review_ids != ids:
        raise ValueError('PDF review and catalog disagree')
    if hashlib.sha256((ROOT / 'Knowledge graph').read_bytes()).hexdigest() != '9c502bdfcc0d5c400c11dd7a78bd9fc3c4b4f07529a973e076d109e28605d67e':
        raise ValueError('Input PDF changed; repeat the source inventory review')
    embedded = {row['url'] for row in json.loads((ROOT / 'data/source/pdf-links.json').read_text())}
    covered = {row['pdf_url'] for row in catalog if row['pdf_url']}
    if embedded != covered:
        raise ValueError(f'Embedded PDF URL coverage mismatch: {embedded ^ covered}')

    parts = [(ROOT / 'docs/research/guide-introduction.md').read_text().rstrip(),
             '\n## Source index\n',
             '| ID | Source | PDF pages | Preferred route / current constraint |',
             '|---|---|---|---|']
    for row in catalog:
        parts.append(f"| [{row['id']}](#{row['id'].lower()}) | {row['name']} | {', '.join(map(str, row['pdf_pages']))} | {row['route_summary']} |")
    for row in catalog:
        content = (ROOT / 'docs/research' / row['notes_file']).read_text()
        sections = re.split(r'^## ', content, flags=re.M)[1:]
        matching = [s.partition('\n')[2].strip() for s in sections if s.partition('\n')[0] == row['notes_heading']]
        if len(matching) != 1:
            raise ValueError(f"{row['id']}: missing or duplicated research section")
        body = matching[0]
        if not re.search(r'\]\(https?://', body):
            raise ValueError(f"{row['id']}: missing linked evidence")
        # Notes sit one directory below the assembled guide.
        body = re.sub(r'\]\(([^():/]+-probes\.json)\)', r'](research/\1)', body)
        parts.extend(['', f'<a id="{row["id"].lower()}"></a>', '',
                      f"## {row['id']} — {row['name']}", '',
                      f"PDF pages: {', '.join(map(str, row['pdf_pages']))}. **Acquisition summary:** {row['route_summary']}", '', body])
    parts.extend(['', '## Next implementation steps', '',
                  'See [additional source recommendations](additional-sources.md) for 16 proposed additions and [the ingestion plan](ingestion-plan.md) for identity resolution, provenance, incremental updates and acceptance criteria. This guide documents acquisition routes; it does not claim that all source data has been harvested.', ''])
    return '\n'.join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Fail if the guide differs from its source notes')
    args = parser.parse_args()
    text = build()
    path = ROOT / 'docs/source-extraction-guide.md'
    if args.check:
        if not path.exists() or path.read_text() != text:
            raise SystemExit('Guide is stale; run python3 scripts/build_source_guide.py')
        print('PASS: 21 source sections, PDF hash, inventory, 18 embedded URLs, citations, and assembled guide freshness')
    else:
        path.write_text(text)
        print(f'Wrote {path} ({len(text.split())} words)')


if __name__ == '__main__':
    main()
