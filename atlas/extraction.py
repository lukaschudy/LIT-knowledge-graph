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
    if not any(s['id']==source_id for s in bundle['sources']):
        raise ValueError('Register source metadata before extracting claims.')
    if not isinstance(proposals,list): raise ValueError('Proposals must be a list.')
    result=deepcopy(bundle)
    known_claims={c['id'] for c in result['claims']}
    snapshot=sha256(source_text.encode()).hexdigest()
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
        if cid in known_claims: continue
        result['claims'].append({k:p[k] for k in ('subject','predicate','object','assertion_type','context')} | {'id':cid,'extraction_confidence':None})
        result['evidence'].append(dict(id='evidence:extracted:'+suffix,claim_id=cid,source_id=source_id,
            locator=f'sha256:{snapshot}; characters [{start},{end})',excerpt=p['excerpt'],stance='supports',review_status='unreviewed'))
        known_claims.add(cid)
    errors=validate_bundle(result)
    if errors: raise ValidationError(errors)
    return result
