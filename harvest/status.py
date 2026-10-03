"""Compact status across the PDF source inventory and all added providers."""
import json
from harvest.core import ROOT,MANIFESTS,now,atomic_json

def snapshot():
    manifests={p.stem:json.loads(p.read_text()) for p in MANIFESTS.glob('*.json')}
    mapping=json.loads((ROOT/'data/harvest-source-map.json').read_text())
    catalog=json.loads((ROOT/'data/source/catalog.json').read_text())
    sources=[]
    for key,m in sorted(manifests.items()):
        sources.append({'source':key,'status':m.get('status'),'datasets':len(m.get('datasets',{})),
            'records':sum(x['records'] for x in m.get('datasets',{}).values()),
            'raw_bytes':sum(x['bytes'] for x in m.get('artifacts',{}).values()),
            'normalized_bytes':sum(x['bytes'] for x in m.get('datasets',{}).values()),
            'scope':m.get('scope'),'coverage':m.get('coverage'),'failure':m.get('failure'),'reason':m.get('reason')})
    original=[]
    for entry in catalog:
        providers=mapping['pdf_sources'].get(entry['id'],[])
        original.append({'id':entry['id'],'name':entry['name'],'providers':[{'source':key,'status':manifests.get(key,{}).get('status','not_started')} for key in providers]})
    return {'generated_at':now(),'pdf_source_coverage':original,'sources':sources,
        'totals':{'records':sum(x['records'] for x in sources),'raw_bytes':sum(x['raw_bytes'] for x in sources),'normalized_bytes':sum(x['normalized_bytes'] for x in sources)},
        'interpretation':'Record totals mix entities, annotations, assertions, XML stanzas and query memberships. Completeness refers only to each declared source scope. Access-dependent providers and query limitations remain explicit.'}

if __name__=='__main__':
    result=snapshot();atomic_json(ROOT/'data/harvest-status.json',result)
    for row in result['sources']:print(f"{row['source']:28} {row['status']:30} {row['records']:>12,} records")
    print(json.dumps(result['totals']))
