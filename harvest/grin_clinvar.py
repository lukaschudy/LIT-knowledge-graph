"""Complete VCV XML for single-gene GRIN2A/GRIN2B variants in the acquired summary."""
import hashlib, time, xml.etree.ElementTree as ET
from urllib.parse import urlencode
from harvest.core import ROOT,PROCESSED,read_records,download,emit_records,update_manifest

def run():
    source='grin_clinvar';path=PROCESSED/'grin_reference/clinvar_variant_summary.jsonl.gz'
    ids=sorted({r['native']['VariationID'] for r in read_records(path) if r['native']['GeneSymbol'] in ('GRIN2A','GRIN2B')},key=int)
    paths=[];seen=set()
    def records():
        for start in range(0,len(ids),200):
            batch=ids[start:start+200]
            params={'db':'clinvar','rettype':'vcv','is_variationid':'true','id':','.join(batch),'tool':'LITRareDiseaseHarvest'}
            url='https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?'+urlencode(params)
            p=download(source,url,'vcv-'+hashlib.sha256(','.join(batch).encode()).hexdigest()[:20]+'.xml',license_name='NCBI ClinVar data; attribution retained, submitter assertion context required')
            paths.append(p)
            root=ET.parse(p).getroot()
            found=[]
            for entry in root.iter('VariationArchive'):
                identifier=entry.get('VariationID');found.append(identifier)
                if identifier not in batch:raise ValueError('Unexpected ClinVar VariationID')
                if identifier in seen:raise ValueError('Duplicate ClinVar VariationID')
                seen.add(identifier)
                yield {'variation_id':identifier,'accession':entry.get('Accession'),'version':entry.get('Version'),'native_xml':ET.tostring(entry,encoding='unicode'),'input_path':str(p.relative_to(ROOT))}
            if set(found)!=set(batch):raise ValueError(f'ClinVar returned {len(found)} of {len(batch)} requested IDs')
            time.sleep(1)
    emit_records(source,'variant_archives',records(),input_paths=[path],description='Complete native VCV records, including assertion/evidence detail. Only exact single-gene GRIN2A/B summary records; not the functionally verified LoF cohort.')
    update_manifest(source,status='complete_for_scope',scope='All single-gene GRIN2A/GRIN2B variation IDs from acquired ClinVar summary snapshot',expected_variants=len(ids),retrieved_variants=len(seen),input_dataset=str(path.relative_to(ROOT)),limitations=['NCBI live VCV version may be newer than monthly summary; both snapshots and dates retained.','Classification is not receptor functional evidence.','Multigene structural variants remain in summary context only.'])
if __name__=='__main__':run()
