"""Create a source-linked research discussion brief from the real GRIN bundle."""
import json
from harvest.core import ROOT,atomic_json,digest
from harvest.grin_bundle import build,OUTPUT
from atlas.reasoning import AtlasReasoner

def run():
    b=build();r=AtlasReasoner(b).explore('cohort:grin2b:core_likely_reduced')
    route=next(o for o in r['opportunities'] if o['asset']['id']=='asset:grin-registry' and o['status']=='supported_route')
    variants=[n['properties'] for n in b['nodes'] if n['type']=='Variant']
    ids=set(route['path_claim_ids']);sources={e['source_id'] for e in b['evidence'] if e['claim_id'] in ids}
    brief={'title':'Shared observational measures for selected GRIN2A/GRIN2B reduced-function variants',
      'status':'draft_for_expert_discussion; not a study protocol, access approval or clinical recommendation',
      'created_at':'2026-10-03','question':'Could existing GRIN registry measures support a functionally stratified observational comparison across selected GRIN2A and GRIN2B variants with published evidence of reduced receptor function?',
      'core_variants':[{'gene':v['gene'],'protein':v['reported_protein'],'source_category':v['integrated_function']['source_classification']} for v in variants if v['strict_reduced_function_inclusion']],
      'separate_groups':[{'gene':v['gene'],'protein':v['reported_protein'],'tier':v['cohort_tier'],'reason':v['integrated_function']['why']} for v in variants if not v['strict_reduced_function_inclusion']],
      'existing_components':[{'name':'GRIN Variant Patient Registry','purpose':'Assess existing data definitions and longitudinal measures, subject to consent and a data-sharing agreement.','source_url':'https://grin2b.com/grin-registry/'},
         {'name':'Published cross-gene outcome assessment methods','purpose':'Review candidate adaptive, cognitive, motor, sleep, quality-of-life, behavior and seizure/EEG domains; select only suitable licensed instruments after clinical review.','source_url':'https://pubmed.ncbi.nlm.nih.gov/38380699/'}],
      'potential_partners':[{'role':'Colorado registry team (Dr. Benke)','public_route':'https://grin2b.com/grin-registry/','basis':'Registry FAQ 1 and 4 name the team and data-sharing contact.'},
         {'role':'Leipzig registry team (Dr. Lemke)','public_route':'https://grin2b.com/grin-registry/','basis':'Registry FAQ 1 and 4 name the team and data-sharing contact.'},
         {'role':'CFERV functional-assay team','public_route':'https://med.emory.edu/departments/pharmacology-chemical-biology/programs-centers/cferv/request-analysis/index.html','basis':'Review published receptor assays and availability of further characterization.'}],
      'proposed_first_milestone':{'deliverable':'An expert-reviewed feasibility matrix linking exact variant identity, assay category, consented aggregate case availability and comparable outcome definitions.',
         'completion_criteria':['Resolve transcript and DNA allele identity without merging same-protein alternate alleles.',
            'Confirm clinical diagnosis and developmental phenotype for potential participants.',
            'Agree how to treat Likely LoF, Possible LoF, opposing and indeterminate assay results.',
            'Obtain aggregate availability counts and confirm lawful access routes; no participant records are requested by this prototype.',
            'Choose common outcome domains and document age, baseline severity, language and follow-up differences.',
            'Determine study design and access requirements with responsible researchers.']},
      'suggested_feasibility_fields':['gene','transcript accession/version','genomic build and allele','protein substitution','primary functional citation','assay model and WT comparator','source functional category','clinical phenotype definition','age band','baseline severity','outcome instrument/version','language','follow-up interval','consent and data-access status'],
      'limits':['Recombinant receptor findings do not establish equivalent circuit effects or clinical trajectories across genes.',
         'The cohort is a curated ten-variant example; it is not all known reduced-function GRIN variants.',
         'Eligible participant counts and availability of specific biobank/model assets remain unknown.',
         'The cited cross-gene study was uncontrolled; it does not establish causal treatment efficacy.',
         'This proposal has not been sent to anyone or reviewed by a disease-area expert.',
         'No speedup or treatment-development impact has been measured.'],
      'supporting_claim_ids':sorted(ids),'citations':[s for s in b['sources'] if s['id'] in sources]+[{'id':'crossgene-methods','url':'https://pubmed.ncbi.nlm.nih.gov/38380699/'}]}
    atomic_json(ROOT/'data/curated/grin_research_proposal.json',brief)
    atomic_json(ROOT/'data/curated/grin_demo_validation.json',{'bundle_sha256':digest(OUTPUT),'dataset_id':b['dataset']['id'],
      'candidate_states':{c['disease']['id']:c['status'] for c in r['candidates']},'supported_assets':[o['asset']['id'] for o in r['opportunities'] if o['status']=='supported_route'],
      'expert_review':'pending','clinical_use':'not validated','browser_journey':'Search GRIN2B → selected Likely LoF cohort → GRIN2A connection → primary evidence → registry access conditions; manually exercised through browser automation.'})
    print('Wrote proposal and validation record.')
if __name__=='__main__':run()
