"""Validate proposed AI extractions before promoting them into an evidence bundle.

This is a model-independent boundary, not an LLM client. It verifies exact source
spans and ontology endpoints, not the scientific truth of an extracted statement.
"""
from copy import deepcopy
from hashlib import sha256
from atlas.model import validate_bundle, ValidationError


def ground_proposals(bundle, *, source_id, source_text, proposals):
    if not isinstance(source_text,str) or not source_text:
        raise ValueError('A nonempty source snapshot is required.')
    source = next((s for s in bundle['sources'] if s['id'] == source_id), None)
    if source is None:
        raise ValueError('Register source metadata before extracting claims.')
    if not isinstance(proposals,list): raise ValueError('Proposals must be a list.')
    result=deepcopy(bundle)
    known_claims={c['id']: c for c in result['claims']}
    known_evidence={e['id']: e for e in result['evidence']}
    snapshot=sha256(source_text.encode()).hexdigest()
    declared_version = source.get('version')
    if declared_version and (declared_version.startswith('sha256:') or len(declared_version) == 64):
        if declared_version.removeprefix('sha256:') != snapshot:
            raise ValueError('Source text does not match its registered snapshot version.')
    evidence_version = declared_version if declared_version and declared_version.removeprefix('sha256:') == snapshot else snapshot
    for index,p in enumerate(proposals):
        if not isinstance(p,dict): raise ValueError(f'Proposal {index} must be an object.')
        required={'subject','predicate','object','assertion_type','context','start','end','excerpt'}
        if set(p)!=required: raise ValueError(f'Proposal {index} must contain exactly {sorted(required)}.')
        start,end=p['start'],p['end']
        if type(start) is not int or type(end) is not int or not (0 <= start < end <= len(source_text)):
            raise ValueError(f'Proposal {index} has invalid source character offsets.')
        if source_text[start:end]!=p['excerpt']:
            raise ValueError(f'Proposal {index} excerpt is not the exact source span.')
        import json
        identity=json.dumps([source_id,snapshot,p],sort_keys=True,ensure_ascii=False)
        suffix=sha256(identity.encode()).hexdigest()[:24]
        cid='claim:extracted:'+suffix
        claim_fields = {k:p[k] for k in ('subject','predicate','object','assertion_type','context')}
        evidence_fields = dict(id='evidence:extracted:'+suffix,claim_id=cid,source_id=source_id,
            locator=f'sha256:{snapshot}; characters [{start},{end})',excerpt=p['excerpt'],stance='supports',review_status='unreviewed',
            source_version=evidence_version)
        if cid in known_claims:
            existing_evidence = known_evidence.get(evidence_fields['id'], {})
            if (any(known_claims[cid].get(k) != value for k, value in claim_fields.items())
                    or any(existing_evidence.get(k) != value for k, value in evidence_fields.items() if k != 'review_status')):
                raise ValueError(f'Proposal {index} collides with altered or missing extracted claim provenance.')
            continue
        new_claim = deepcopy(claim_fields) | {'id':cid,'extraction_confidence':None}
        result['claims'].append(new_claim)
        result['evidence'].append(evidence_fields)
        known_claims[cid] = new_claim
        known_evidence[evidence_fields['id']] = evidence_fields
    errors=validate_bundle(result)
    if errors: raise ValidationError(errors)
    return result
