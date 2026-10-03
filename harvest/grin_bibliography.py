"""Publisher-deposited DOI metadata for every cited functional-evidence paper."""
import hashlib,json
from urllib.parse import quote
from harvest.core import ROOT,download,emit_records,update_manifest

def run():
    evidence=ROOT/'data/curated/grin_functional_evidence.json'
    data=json.loads(evidence.read_text());results=[];failures=[];paths=[]
    dois=sorted({s['doi'].lower().removeprefix('https://doi.org/') for s in data['sources'] if s.get('doi')})
    for doi in dois:
        try:
            url='https://api.crossref.org/works/'+quote(doi,safe='')
            p=download('crossref_grin',url,hashlib.sha256(doi.encode()).hexdigest()[:20]+'.json',license_name='Crossref metadata; abstracts may carry publisher copyright')
            obj=json.loads(p.read_text());r=obj.get('message')
            if obj.get('status')!='ok' or not isinstance(r,dict) or r.get('DOI','').lower()!=doi:raise ValueError('Unexpected Crossref DOI result')
            paths.append(p);results.append(r)
        except Exception as e:failures.append({'doi':doi,'error':str(e)})
    if results:emit_records('crossref_grin','cited_works',results,input_paths=paths+[evidence],description='Exact DOI records for the curated functional evidence sources, retaining publisher relation/update metadata, ORCID and funder identifiers.')
    update_manifest('crossref_grin',status='partial' if failures else 'complete_for_scope',scope='Every DOI in the curated GRIN functional-evidence source list',queried_dois=dois,failures=failures,limitations=['Missing retraction/correction metadata does not establish that no notice exists.','Author names are not merged into identities without explicit identifiers.'])
if __name__=='__main__':run()
