"""Acquire the small official source set for the curated GRIN resource map."""
import hashlib,json
from harvest.core import ROOT,download,emit_records,update_manifest

def run():
    p=ROOT/'data/curated/grin_resources.json';data=json.loads(p.read_text());inputs=[];unavailable=[]
    for url in sorted({x['source_url'] for x in data['resources']+data['announcements']}):
        try:
            artifact=download('grin_resources',url,hashlib.sha256(url.encode()).hexdigest()[:16]+'.html',license_name='Provider website copyright; local research snapshot, curated factual metadata and source links; no blanket text redistribution grant')
            if 'body { visibility: hidden' in artifact.read_text():raise ValueError('HTML response is a browser challenge, not article content')
            inputs.append(artifact)
        except (RuntimeError,ValueError) as e:
            unavailable.append({'url':url,'error':str(e),'evidence_route':'Official page reviewed through web search/open; no local HTML snapshot available'})
    emit_records('grin_resources','resources',data['resources'],input_paths=inputs+[p],description='Curated public GRIN resource facts; scope/access/availability uncertainties retained. Metadata only.')
    emit_records('grin_resources','announcements',data['announcements'],input_paths=inputs+[p],description='Issuer announcement metadata; projected research is not a validated result.')
    trial=download('grin_resources','https://clinicaltrials.gov/api/v2/studies/NCT04646447','NCT04646447.json',license_name='ClinicalTrials.gov terms of use; preserve submitted record and update dates')
    native=json.loads(trial.read_text())
    if native.get('protocolSection',{}).get('identificationModule',{}).get('nctId')!='NCT04646447':raise ValueError('Unexpected trial response')
    emit_records('grin_resources','study_records',[native],input_paths=[trial],description='Complete native trial record for the published cross-gene study; not an eligibility or treatment recommendation.')
    update_manifest('grin_resources',status='complete_for_scope',scope=data['scope'],unavailable_local_snapshots=unavailable,curation='Assistant-curated source facts; expert and provider review pending. No contact, application or enrollment submitted.')
if __name__=='__main__':run()
