"""Transparent cohort membership and assay-normalized features, without imputation."""
from __future__ import annotations
import csv,json,re
from collections import Counter
from harvest.core import ROOT,atomic_json
from harvest.grin_bundle import EVIDENCE,core_eligible

def central_value(value):
    if value is None:return None
    match=re.match(r'^\s*([+-]?\d[\d,]*(?:\.\d+)?)',value)
    return float(match.group(1).replace(',','')) if match else None

def normalized_feature(parameter):
    variant=central_value(parameter.get('variant'));wt=central_value(parameter.get('wt_control'))
    if variant is None or wt in (None,0):return None
    # Potency is inverse EC50; all other measures retain variant/WT direction.
    if parameter['name'] in ('glutamate EC50','glycine EC50'):
        return None if variant==0 else {'ratio':wt/variant,'definition':'WT EC50 / variant EC50 (agonist potency)'}
    return {'ratio':variant/wt,'definition':'variant central value / WT central value'}

def build(e):
    sources={s['source_id']:s for s in e['sources']};rows=[];members=[]
    for v in e['variants']:
        core=core_eligible(v,sources)
        members.append({'variant_id':v['variant_id'],'gene':v['gene'],'protein':v['reported_protein'],
                        'tier':v['cohort_tier'],'core_member':core,'reported_classification':v['integrated_function']['source_classification'],
                        'classification_source':sources[v['integrated_function']['source_id']]['url'],
                        'review_status':'expert_review_pending'})
        for assay in v['functional_evidence']:
            for p in assay['measured_parameters']:
                f=normalized_feature(p)
                rows.append({'variant_id':v['variant_id'],'gene':v['gene'],'protein':v['reported_protein'],'tier':v['cohort_tier'],
                             'source_id':assay['source_id'],'locator':assay['evidence_location'],'parameter':p['name'],
                             'variant_raw':p['variant'],'wt_raw':p['wt_control'],'unit':p['unit'],'variant_n':p['n'],
                             'normalized_ratio':None if f is None else f['ratio'],'ratio_definition':None if f is None else f['definition'],
                             'ratio_status':'not_calculable' if f is None else 'derived_from_reported_central_values',
                             'source_url':sources[assay['source_id']]['url']})
    return {'schema_version':'grin-cluster-v1','method':'Published functional-category gate with primary assay evidence; deterministic, not unsupervised discovery.',
            'unit_of_analysis':'variant-level receptor assay; not a patient','members':members,'tier_counts':dict(Counter(v['tier'] for v in members)),
            'assay_features':rows,'limitations':['Ratios use published central values; uncertainty is not propagated and no significance is recomputed.',
            'Missing measurements remain null. Assays from different papers retain separate rows and WT comparators.',
            'Lower or higher current/surface expression alone does not establish integrated functional direction.',
            'Cohort is a selected ten-variant demonstration, not all published GRIN functional variants.',
            'Clinical diagnoses, developmental context and eligibility require independent expert review.']}

def main():
    d=build(json.loads(EVIDENCE.read_text()));atomic_json(ROOT/'data/curated/grin_cluster.json',d)
    path=ROOT/'data/curated/grin_assay_features.csv'
    with path.open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(d['assay_features'][0]));writer.writeheader();writer.writerows(d['assay_features'])
    print(json.dumps({'members':len(d['members']),'tiers':d['tier_counts'],'assay_features':len(d['assay_features'])}))
if __name__=='__main__':main()
