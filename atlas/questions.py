"""Small, explicit graph lookup answers. No language model or external requests."""
from __future__ import annotations
import re
from typing import Any

REASONS = {
    "reported_mechanism_paths_have_supporting_evidence_and_matching_effect": "Their reported mechanism paths have supporting evidence and matching effect contexts.",
    "opposite_effect_contexts_disqualify_shared_mechanism": "Their variant effects point in opposite directions, so the shared mechanism does not support a research route.",
    "effect_context_missing_or_unknown_requires_review": "The effect context is missing or unknown and needs review.",
    "mechanistic_path_has_contradicting_evidence": "The mechanism path has contradictory evidence.",
    "mechanistic_path_lacks_reported_supported_evidence": "The mechanism path lacks reported, supported evidence.",
    "phenotype_overlap_alone_is_insufficient_without_a_supported_shared_mechanism": "Phenotype overlap alone does not establish a supported mechanism connection.",
    "mechanistic_evidence_requires_review": "The mechanism evidence needs review.",
    "biological_context_differs_or_is_incomplete": "The biological context differs or is incomplete.",
    "negative_assertion_is_not_positive_mechanism_evidence": "A negative assertion cannot support a positive mechanism connection.",
}


def answer_question(bundle: dict[str, Any], reasoner: Any, question: str, context: str | None = None, claim_context: list[str] | None = None) -> dict[str, Any]:
    nodes = {n['id']: n for n in bundle['nodes']}
    claims = {c['id']: c for c in bundle['claims']}
    q = question.casefold().strip()
    selected = nodes.get(context or '')
    found = []
    for n in nodes.values():
        terms = [n['label'], *n.get('aliases', [])]
        matches = [len(t) for t in terms if len(t) > 2 and re.search(r'(?<!\w)' + re.escape(t.casefold()) + r'(?!\w)', q)]
        if matches:
            found.append((max(matches), n))
    found.sort(key=lambda item: -item[0])
    mentioned = [n for _, n in found]
    if mentioned:
        selected = mentioned[0]
    disease_nodes = [n for n in mentioned if n['type'] == 'Disease']
    if context in nodes and nodes[context]['type'] == 'Disease' and context not in [n['id'] for n in disease_nodes]:
        disease_nodes.append(nodes[context])

    def result(answer: str, ids=(), node_ids=(), suggestions=(), missing=False):
        valid = list(dict.fromkeys(c for c in ids if c in claims))
        return {**({'proposal': {'query': question, 'entry': 'chat'}} if missing else {}), 'answer': answer, 'claim_ids': valid, 'node_ids': list(dict.fromkeys(node_ids)),
                'suggestions': list(suggestions), 'mode': 'graph_lookup', 'synthetic': bool(bundle['dataset']['synthetic'])}

    if re.search(r'\b(treat|treatment|cure|dose|dosage|medication|diagnose|diagnosis|take a drug)\b', q):
        return result('This atlas can show research connections and their evidence. It cannot determine a diagnosis or recommend treatment. A shared mechanism does not establish that a treatment transfers between diseases.')

    if claim_context and not mentioned and re.search(r'\b(evidence|sources?|support|proof|papers?)\b', q):
        ids = set(claim_context) & claims.keys()
        rows = [e for e in bundle['evidence'] if e['claim_id'] in ids]
        supporting = sum(e['stance'] == 'supports' for e in rows)
        conflicting = sum(e['stance'] == 'contradicts' for e in rows)
        source_count = len({e['source_id'] for e in rows})
        supporting_label = 'record' if supporting == 1 else 'records'
        conflicting_label = 'record' if conflicting == 1 else 'records'
        return result(f'The linked assertions have {supporting} supporting {supporting_label} and {conflicting} counter-evidence {conflicting_label} across {source_count} sources. These records describe the individual claims, not proof that the overall research route is compatible. Open a citation to inspect its excerpt and context.', claim_context)

    if len(disease_nodes) >= 2:
        first, second = disease_nodes[:2]
        route = reasoner.explore(first['id'])
        candidate = next((c for c in route.get('candidates', []) if c['disease']['id'] == second['id']), None)
        if not candidate:
            return result(f"No candidate route between {first['label']} and {second['label']} is recorded in this dataset. This is a coverage gap, not proof that no connection exists.", node_ids=[first['id'], second['id']], missing=True)
        status = {'supported_lead': 'a supported research lead', 'needs_review': 'a connection requiring review', 'rejected': 'an unsupported route'}.get(candidate['status'], 'an unsupported route')
        reasons = [REASONS[r] for r in candidate.get('reasons', []) if r in REASONS]
        return result(f"{first['label']} and {second['label']}: {status}. " + ' '.join(reasons) + ' This is a research assessment, not clinical compatibility.', candidate.get('path_claim_ids', []), [first['id'], second['id']], ['What evidence supports this?'])

    if re.search(r'\b(conflict|conflicting|contradict|contradiction|uncertain)\w*\b', q):
        ids = {e['claim_id'] for e in bundle['evidence'] if e['stance'] == 'contradicts'}
        if selected:
            relevant = {selected['id']} | {c['object'] for c in claims.values() if c['subject'] == selected['id'] and c['predicate'] == 'HAS_VARIANT'}
            ids = {cid for cid in ids if claims[cid]['subject'] in relevant or claims[cid]['object'] in relevant}
        scope = f" for {selected['label']}" if selected else ''
        return result(f"{len(ids)} claim(s) with counter-evidence are recorded{scope}. Open the evidence to compare the source excerpts." if ids else f"No counter-evidence is recorded{scope}. That does not establish certainty or complete coverage.", sorted(ids), [selected['id']] if selected else [])

    if re.search(r'\b(asset|assets|resource|resources|reuse|reusable|partner|partners)\b', q):
        if selected and selected['type'] == 'Disease':
            route = reasoner.explore(selected['id'])
            leads = [o for o in route.get('opportunities', []) if o['status'] == 'supported_route']
            if leads:
                names = '; '.join(dict.fromkeys(o['asset']['label'] for o in leads))
                return result(f"Research asset to investigate: {names}. Access and suitability still need review; shared biology does not establish transferability.", [cid for o in leads for cid in o.get('path_claim_ids', [])], [o['asset']['id'] for o in leads])
            return result(f"No fully evidenced asset-and-maintainer route is recorded for {selected['label']}. More evidence or ownership information is needed.", node_ids=[selected['id']], missing=True)
        assets = [n for n in nodes.values() if n['type'] == 'Asset']
        return result('Recorded research assets: ' + '; '.join(n['label'] for n in assets) + '. Select one to inspect its recorded relationships.' if assets else 'No research assets are recorded in this dataset.', [c['id'] for c in claims.values() if any(n['id'] in (c['subject'], c['object']) for n in assets)], [n['id'] for n in assets])

    if selected:
        connected = [c for c in claims.values() if selected['id'] in (c['subject'], c['object'])]
        if re.search(r'\b(evidence|source|sources|support|proof|paper|papers)\b', q):
            variants = {c['object'] for c in connected if c['subject'] == selected['id'] and c['predicate'] == 'HAS_VARIANT'}
            related = connected + [c for c in claims.values() if c['subject'] in variants and c['predicate'] == 'HAS_EFFECT']
            ids = {c['id'] for c in related}
            rows = [e for e in bundle['evidence'] if e['claim_id'] in ids]
            sources = {e['source_id'] for e in rows}
            counter = sum(e['stance'] == 'contradicts' for e in rows)
            counter_label = "record" if counter == 1 else "records"
            return result(f"{selected['label']}: {len(rows)} evidence records across {len(sources)} sources; {counter} counter-evidence {counter_label}. Each linked claim below opens the original excerpt, context and review status.", [c['id'] for c in related], [selected['id']], missing=not rows)
        if selected['type'] == 'Disease' and re.search(r'\b(connect|connected|connection|connections|related|why|similar)\b', q):
            route = reasoner.explore(selected['id'])
            leads = [c for c in route.get('candidates', []) if c['status'] == 'supported_lead']
            review = [c for c in route.get('candidates', []) if c['status'] == 'needs_review']
            answer = f"{selected['label']}: "
            answer += 'supported research leads with ' + ', '.join(c['disease']['label'] for c in leads) + '.' if leads else 'no supported research lead in this dataset.'
            if review:
                answer += ' Needs review: ' + ', '.join(c['disease']['label'] for c in review) + '.'
            answer += ' A drawn link records an assertion; it does not by itself establish compatibility.'
            return result(answer, [cid for c in leads + review for cid in c.get('path_claim_ids', [])], [selected['id']] + [c['disease']['id'] for c in leads + review])
        if re.search(r'\b(connect|connected|connection|connections|related)\b', q):
            adjacent = list(dict.fromkeys(c['object'] if c['subject'] == selected['id'] else c['subject'] for c in connected))
            names = '; '.join(nodes[n]['label'] for n in adjacent[:8])
            answer = f"Recorded neighbors of {selected['label']}: {names}." if adjacent else f"No linked assertions are recorded for {selected['label']}."
            return result(answer + ' Inspect the claims for direction, context and uncertainty.', [c['id'] for c in connected], [selected['id'], *adjacent], missing=not adjacent)
        if re.search(r'\b(what|tell|describe|about|show|who)\b', q) or q in [t.casefold() for t in [selected['label'], *selected.get('aliases', [])]]:
            description = selected.get('properties', {}).get('description', '')
            return result(f"{selected['label']} is recorded as {selected['type'].lower()}. {description} {len(connected)} linked assertions are available for inspection.", [c['id'] for c in connected], [selected['id']], ['What is connected?', 'What evidence is recorded?', 'Any conflicting evidence?'])

    if re.search(r'\b(overview|graph|atlas|start|here|explore)\b', q) and not selected:
        return result(f"This graph contains {len(nodes)} entities and {len(claims)} recorded assertions. Select a node, then ask about its connections, evidence, or research assets. Proximity is only a layout choice, not a measure of scientific similarity.", suggestions=['What research assets are recorded?', 'Any conflicting evidence?'])
    return result('I can look up connections, evidence and research assets in this graph. Select a node or name an entity, then ask about one of those. This is a graph lookup, not a general-purpose AI answer.', suggestions=['What is in this graph?', 'What research assets are recorded?'], missing=True)
