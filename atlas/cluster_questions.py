"""Deterministic, source-linked answers over the reviewed GRIN annotations."""
import re
from urllib.parse import quote

TIERS = {"core_likely_reduced": "core likely reduced function",
         "provisional_possible_reduced": "provisional possible reduced function",
         "opposing_control": "opposing-function control", "unresolved_control": "unresolved control"}
AMINO = dict(Ala="A", Arg="R", Asn="N", Asp="D", Cys="C", Gln="Q", Glu="E", Gly="G", His="H", Ile="I", Leu="L", Lys="K", Met="M", Phe="F", Pro="P", Ser="S", Thr="T", Trp="W", Tyr="Y", Val="V")
ENDPOINTS = {"glutamate_ec50", "glycine_ec50", "open_probability", "weighted_deactivation_tau", "peak_current_density"}


def short_protein(protein):
    return re.sub(r"[A-Z][a-z]{2}", lambda m: AMINO.get(m[0], m[0]), protein.removeprefix("p."))


def grin2b_overview(cluster):
    """Bounded graph summary plus separately curated public support signposts."""
    members = [v for v in cluster['members'] if v['gene'] == 'GRIN2B']
    counts = {tier: sum(v['tier'] == tier for v in members) for tier in TIERS}
    classifications = [c for c in cluster['claims'] if c['gene'] == 'GRIN2B'
                       and c['predicate'] == 'author_functional_classification' and c['evidence_type'] == 'primary_report']
    docs = {c['document_id'] for c in classifications}
    sections = [
        {'title': 'What this graph knows', 'text':
         f"GRIN2B is recorded here with source-linked evidence for {len(members)} selected protein variants: "
         f"{counts['core_likely_reduced']} core likely reduced-function, {counts['provisional_possible_reduced']} provisional, "
         f"{counts['opposing_control']} opposing-function controls and {counts['unresolved_control']} unresolved control. "
         "These categories describe individual variants, not the whole gene.", 'links': []},
        {'title': 'What the evidence means', 'text':
         "For example, S541R is in the core group; C461F remains provisional because the source-reported integrated classification is Possible LoF. "
         "The graph retains experimental comparisons with wild type and conflicting reports. This is a selected research snapshot; AI source audit is complete and expert review is pending.",
         'links': [{'label': 'Compare S541R evidence', 'url': '/cluster?variant=GRIN2B%3Ap.Ser541Arg'},
                   {'label': 'Read C461F evidence', 'url': '/cluster?variant=GRIN2B%3Ap.Cys461Phe'}]},
        {'title': 'Where to seek help', 'text':
         "For personal care, discuss the exact variant with a clinical genetics or neurology team. These external resources offer different kinds of support:",
         'links': [
             {'label': 'GRIN2B Foundation — family support', 'url': 'https://grin2b.com/connect-with-us/',
              'description': 'Connect with the parent and caregiver community.'},
             {'label': 'Simons Searchlight — gene guide and research', 'url': 'https://www.simonssearchlight.org/research/what-we-study/grin2b/',
              'description': 'Learn about GRIN2B and voluntary research participation.'},
             {'label': 'GRIN2B Foundation — researcher resources', 'url': 'https://grin2b.com/for-researchers/',
              'description': 'Find research resources and listed clinical centers; contact them about access.'}
         ]}
    ]
    return {'answer': '\n\n'.join(s['title'] + '\n' + s['text'] for s in sections),
            'sections': sections, 'mode': 'curated_gene_overview', 'synthetic': False,
            'claim_ids': [], 'node_ids': [v['id'] for v in members], 'suggestions': [],
            'annotation_claim_ids': [c['id'] for c in classifications],
            'citations': [s for s in cluster['sources'] if s['document_id'] in docs],
            'reference_sha256': cluster['reference_sha256'],
            'support_resources': {'checked_on': '2026-10-04', 'status': 'external_signposts_not_graph_claims'}}


def answer_cluster_question(cluster, question, context=None):
    q = question.casefold()
    if re.search(r"\b(treat|treatment|cure|dose|dosage|medication|diagnose|diagnosis)\b", q):
        return None  # The shared graph handler retains its clinical-request boundary.
    genes = {g for g in ("GRIN2A", "GRIN2B") if g.casefold() in q}
    members = [v for v in cluster["members"] if (not genes or v["gene"] in genes)
               and any(re.search(r"(?<!\w)" + re.escape(t.casefold()) + r"(?!\w)", q)
                       for t in (v["protein"], v["protein"].removeprefix("p."), short_protein(v["protein"])))]
    requested = re.findall(r"(?<!\w)(?:p\.)?(?:[A-Z][a-z]{2}\d+[A-Z][a-z]{2}|[A-Z]\d+[A-Z])(?!\w)", question, re.I)
    known = {t.casefold() for v in members for t in (v['protein'], v['protein'].removeprefix('p.'), short_protein(v['protein']))}
    missing = [t for t in requested if t.casefold().removeprefix('p.') not in known]
    if missing:
        return {'answer': 'This reviewed cluster has no record for ' + ', '.join(missing) +
                '. This is a coverage gap, not evidence that the variant has no effect. You can propose an addition with a published source for review.',
                'mode': 'source_annotation_lookup', 'synthetic': False, 'claim_ids': [],
                'node_ids': [], 'suggestions': [], 'proposal': {'query': question, 'entry': 'chat'}}
    if (genes == {'GRIN2B'} and not requested and not members
            and not any(v['id'] == context for v in cluster['members'])
            and re.search(r"\b(known|overview|help|support)\b", q)):
        return grin2b_overview(cluster)
    if not members and context:
        members = [v for v in cluster["members"] if v["id"] == context]
    overview = re.search(r"\b(cluster|variants|annotations|observations)\b", q)
    if not members and not overview:
        return None
    sources = {s["document_id"]: s for s in cluster["sources"]}
    rows, used_claims, used_docs, links, paragraphs = [], [], set(), [], []
    if not members:
        members = [v for v in cluster["members"] if not genes or v["gene"] in genes]
        paragraphs.append(f"This reviewed development cluster contains {cluster['counts']['variants']} selected variants, {cluster['counts']['observations']} observations and {cluster['counts']['claims']} claims across {cluster['counts']['documents']} papers.")
        paragraphs.extend(f"{v['gene']} {v['protein']}: {TIERS[v['tier']]}" for v in members)
    else:
        paragraphs.append("Membership follows the source-reported integrated classification. Core inclusion requires Likely LoF plus an eligible measured WT comparison; Possible LoF remains provisional. No single measurement or drug response determines membership.")
        for v in members:
            same = lambda r: (r["gene"], r["protein"]) == (v["gene"], v["protein"])
            classifications = [c for c in cluster["claims"] if same(c) and c["predicate"] == "author_functional_classification" and c["evidence_type"] == "primary_report"]
            paragraphs.append(f"{v['gene']} {v['protein']} — {TIERS[v['tier']]}. " + " ".join(f"{c['statement']} [{c['document_id']}]" for c in classifications))
            used_claims.extend(c["id"] for c in classifications)
            used_docs.update(c["document_id"] for c in classifications)
            obs = [o for o in cluster["observations"] if same(o)]
            measured = [o for o in obs if o["table_id"] and o["measurement_type"] == "measured" and o["endpoint"] in ENDPOINTS]
            def value(m):
                if m is None: return "not reported"
                return m["raw"] + (" " + m["unit"] if m["unit"] and m["unit"] not in m["raw"] else "")
            if measured:
                lines = []
                for o in measured:
                    lines.append(f"• {o['endpoint'].replace('_', ' ')}: variant {value(o['measurement'])}; WT {value(o['comparator']['measurement'])}. {o['conditions']['system'] or 'System unreported'}. [{o['document_id']}]")
                paragraphs.append("Selected main-table measurements (raw uncertainty and n retained):\n" + "\n".join(lines))
                rows.extend(measured)
            calculated = [o for o in obs if o["measurement_type"] == "author_calculated" and o["endpoint"] in {"synaptic_charge_transfer", "nonsynaptic_charge_transfer"}]
            if calculated:
                paragraphs.append("Author-calculated predictions, not direct measurements:\n" + "\n".join(f"• {o['endpoint'].replace('_', ' ')}: {value(o['measurement'])}. [{o['document_id']}]" for o in calculated))
                rows.extend(calculated)
            relevant_docs = {o["document_id"] for o in obs} | {c["document_id"] for c in classifications}
            issues = [i for i in cluster["issues"] if same(i) or i["gene"] is None and i["document_id"] in relevant_docs]
            if issues:
                paragraphs.append("Unresolved evidence and protocol issues:\n" + "\n".join(f"• {i['description']} [{i['document_id']}]" for i in issues))
                used_docs.update(i["document_id"] for i in issues)
    for v in members:
        links.append({"label": f"All observations: {v['gene']} {v['protein']}", "url": "/cluster?variant=" + quote(v["gene"] + ":" + v["protein"])})
    used_docs.update(o["document_id"] for o in rows)
    paragraphs.append("AI source-audited; expert review pending. Records may reuse earlier experiments. Unavailable supplements and unquantified figures remain coverage gaps. These are source-reported research categories, not clinical conclusions or a held-out accuracy score.")
    return {"answer": "\n\n".join(paragraphs), "mode": "source_annotation_lookup", "synthetic": False,
            "claim_ids": [], "node_ids": [v["id"] for v in members], "suggestions": [],
            "observation_ids": [o["id"] for o in rows], "annotation_claim_ids": used_claims,
            "citations": [sources[d] for d in sorted(used_docs)], "evidence_links": links,
            "reference_sha256": cluster["reference_sha256"]}
