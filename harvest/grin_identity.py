"""Explicit, non-destructive identity candidates against the acquired ClinVar snapshot."""
import json,re
from harvest.core import ROOT,PROCESSED,read_records,atomic_json
from harvest.grin_bundle import EVIDENCE

def run():
    evidence=json.loads(EVIDENCE.read_text());pool=list(read_records(PROCESSED/'grin_reference/clinvar_variant_summary.jsonl.gz'));out=[]
    for v in evidence['variants']:
        matches={}
        for wrapper in pool:
            r=wrapper['native']
            if r['GeneSymbol']!=v['gene'] or '('+v['reported_protein']+')' not in r['Name']:continue
            key=r['VariationID'];match=matches.setdefault(key,{'variation_id':key,'name':r['Name'],'url':'https://www.ncbi.nlm.nih.gov/clinvar/variation/'+key+'/',
                'reported_cdna_matches':v['reported_cdna']+' ' in r['Name'],'assemblies':[],'reference_rows':[]})
            match['reference_rows'].append(wrapper['_record'])
            match['assemblies'].append({k:r.get(k) for k in ('Assembly','ChromosomeAccession','Start','Stop','PositionVCF','ReferenceAlleleVCF','AlternateAlleleVCF')})
        exact=[r for r in matches.values() if r['reported_cdna_matches']]
        status='source_notation_conflict' if v.get('identity_status')=='publication_cdna_protein_discrepancy' else 'candidate_match_transcript_unresolved' if exact else 'no_match_in_acquired_summary'
        out.append({'curated_variant_id':v['variant_id'],'reported_gene':v['gene'],'reported_protein':v['reported_protein'],'reported_cdna':v['reported_cdna'],
                    'source_transcript':v['transcript_accession'],'status':status,'automatic_merge_allowed':False,'candidates':list(matches.values())})
    atomic_json(ROOT/'data/curated/grin_identity_candidates.json',{'schema_version':'grin-identity-v1','source':'data/processed/harvest/grin_reference/clinvar_variant_summary.jsonl.gz',
        'policy':'Candidate names must match gene and protein exactly. Transcript is unresolved in curated primary-source records; never auto-merge a DNA allele on protein name alone. ClinVar clinical significance is not functional evidence.',
        'records':out})
    print({r['reported_protein']:r['status'] for r in out})
if __name__=='__main__':run()
