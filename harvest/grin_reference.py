"""Exact-identifier GRIN2A/GRIN2B slices of already acquired reference data.

These are reference annotations, not the functionally verified demo cohort.
"""
import re
from harvest.core import PROCESSED,read_records,emit_records,update_manifest
GENES={'GRIN2A','GRIN2B'}
HGNC={'HGNC:4585','HGNC:4586'}
PROTEINS={'Q12879','Q13224'}

def selected(row,keys,values):
    return any(values.intersection(re.split(r'[|;,\s]+',str(row.get(key,'')))) for key in keys)

def run():
    jobs=[
        ('hgnc','hgnc_complete_set',['symbol'],GENES),
        ('clinvar','variant_summary',['GeneSymbol'],GENES),
        ('hpo','genes_to_disease',['gene_symbol'],GENES),
        ('hpo','genes_to_phenotype',['gene_symbol'],GENES),
        ('clingen','gene_disease_validity',['GENE ID (HGNC)'],HGNC),
        ('clingen','gene_disease_validity_lumping_splitting',['GENE ID (HGNC)'],HGNC),
        ('clingen','gene_dosage',['HGNC ID'],HGNC),
        ('gencc','assertions',['gene_curie'],HGNC),
        ('reactome','UniProt2Reactome_All_Levels',['uniprot_accession'],PROTEINS),
        ('go','human_annotations',['db_object_id'],PROTEINS),
    ]
    disease_ids=set()
    for source,name,keys,values in jobs:
        p=PROCESSED/source/(name+'.jsonl.gz')
        if not p.exists():raise FileNotFoundError(p)
        def records():
            for r in read_records(p):
                if selected(r,keys,values):
                    native={k:v for k,v in r.items() if not k.startswith('_')}
                    if source=='hpo' and name=='genes_to_disease':disease_ids.add(r['disease_id'])
                    yield {'upstream_source':source,'upstream_dataset':name,'upstream_record':r['_record'],'native':native}
        emit_records('grin_reference',source+'_'+name,records(),input_paths=[p],description='Exact GRIN2A/GRIN2B identifier slice, including uncertain/conflicting annotations. Membership is NOT evidence of reduced receptor function.')
    p=PROCESSED/'hpo/disease_phenotype_annotations.jsonl.gz'
    emit_records('grin_reference','hpo_disease_phenotypes',({'upstream_record':r['_record'],'native':{k:v for k,v in r.items() if not k.startswith('_')}} for r in read_records(p) if r['database_id'] in disease_ids),input_paths=[p],description='Phenotypes for diseases linked to GRIN2A/B in HPO genes_to_disease. Preserve NOT; disease-level annotations are not specific to a variant or LoF subgroup.')
    update_manifest('grin_reference',status='complete_for_scope',scope='Exact gene/protein identifier slices of acquired reference snapshots; full native records retained. Independent curated functional evidence is required for demo inclusion.',gene_symbols=sorted(GENES),hgnc_ids=sorted(HGNC),uniprot_ids=sorted(PROTEINS),disease_ids=sorted(disease_ids))
if __name__=='__main__':run()
