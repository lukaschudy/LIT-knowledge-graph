"""Build a small, real-data Atlas bundle from curated GRIN evidence.

No clinical classifications are inferred from gene identity or ClinVar.
The Disease nodes explicitly represent selected research cohorts, not new nosology.
"""
from __future__ import annotations
import json, re
from pathlib import Path
from harvest.core import ROOT, atomic_json

EVIDENCE=ROOT/'data/curated/grin_functional_evidence.json'
RESOURCES=ROOT/'data/curated/grin_resources.json'
OUTPUT=ROOT/'data/curated/grin_atlas_bundle.json'
DATE='2026-10-03'
MECHANISM='mechanism:nmda-receptor-signaling'

def slug(value):return re.sub(r'[^a-z0-9]+','-',value.lower()).strip('-')

def core_eligible(v, sources):
    """A conservative deterministic gate; this does not re-adjudicate the paper."""
    interpretation=v.get('integrated_function',{})
    if interpretation.get('source_classification')!='Likely LoF':return False
    if interpretation.get('source_id') not in sources:return False
    if v.get('identity_status')=='publication_cdna_protein_discrepancy':return False
    return any(e.get('source_id') in sources and e.get('assay') and e.get('model')
               and e.get('evidence_location') and any(p.get('variant') is not None and p.get('wt_control')
               for p in e.get('measured_parameters',[])) for e in v.get('functional_evidence',[]))

def build(evidence=None, resources=None):
    evidence=evidence or json.loads(EVIDENCE.read_text())
    resources=resources or json.loads(RESOURCES.read_text())
    b={'schema_version':'1.0','dataset':{'id':'grin-reduced-function-2026-10-03','title':'GRIN research connections — published variant evidence',
       'description':'Selected GRIN2A/GRIN2B research cohorts: six Likely LoF variants, one provisional Possible LoF case and three controls. Real source facts; expert interpretation pending. Research planning only.',
       'synthetic':False,'created_at':DATE},'nodes':[],'sources':[],'claims':[],'evidence':[],'coverage':[]}
    ids=set()
    def node(id,type,label,aliases=(),**properties):
        if id not in ids:b['nodes'].append(dict(id=id,type=type,label=label,aliases=list(aliases),properties=properties));ids.add(id)
        return id
    def source(id,title,url,kind='paper',published_at=None,license='Source-specific rights; factual metadata and paraphrases only'):
        b['sources'].append(dict(id=id,title=title,url=url,kind=kind,retrieved_at=DATE,published_at=published_at,license=license,synthetic=False))
    def claim(subject,predicate,object,source_id,locator,excerpt,context=None,assertion='reported',review='machine_checked'):
        id=f'claim:{len(b["claims"])+1:03d}'
        b['claims'].append(dict(id=id,subject=subject,predicate=predicate,object=object,assertion_type=assertion,context=context or {},extraction_confidence=None))
        b['evidence'].append(dict(id=f'evidence:{len(b["evidence"])+1:03d}',claim_id=id,source_id=source_id,locator=locator,excerpt=excerpt,stance='supports',review_status=review))
        return id
    sources={s['source_id']:s for s in evidence['sources']}
    for s in sources.values():
        source('paper:'+s['source_id'],s['title'],s['url'])
        node('publication:'+s['source_id'],'Publication',s['title'],doi=s['doi'],pmid=s['pmid'],pmcid=s['pmcid'])
    node(MECHANISM,'Mechanism','NMDA receptor signaling',description='Direction is variant-specific and carried on evidence claims. Shared direction is a research connection, not clinical equivalence.')
    cohort_ids={}
    tier_labels={'core_likely_reduced':'selected Likely LoF variants','provisional_possible_reduced':'provisional Possible LoF case',
                 'opposing_control':'opposing-function controls','unresolved_control':'unresolved-function control'}
    for v in evidence['variants']:
        tier=v['cohort_tier']
        if v['strict_reduced_function_inclusion']!=core_eligible(v,sources):raise ValueError('Core gate inconsistent: '+v['variant_id'])
        gene=v['gene'];cohort=f'cohort:{gene.lower()}:{tier}'
        cohort_ids[(gene,tier)]=cohort
        node(cohort,'Disease',f'{gene}-related neurodevelopmental disorder — {tier_labels[tier]}',
             aliases=[gene] if tier=='core_likely_reduced' else [gene+' '+tier_labels[tier]],
             gene=gene,entity_scope='selected_variant_research_cohort',cohort_tier=tier,
             description='Membership is limited to explicitly selected variants; it is not a claim about every person with this diagnosis.',expert_review='pending')
        node('gene:'+gene,'Gene',gene,aliases=['GluN2A' if gene=='GRIN2A' else 'GluN2B'],hgnc_id='HGNC:4585' if gene=='GRIN2A' else 'HGNC:4586')
        vid=node('variant:'+slug(v['variant_id']),'Variant',gene+' '+v['reported_protein'],aliases=[v['reported_protein']],**v)
        clinical=v['clinical_association'];sid='paper:'+clinical['source_ids'][0]
        claim(cohort,'HAS_VARIANT',vid,sid,clinical['evidence_location'],
              'Paraphrase: the source reports this variant in people with '+', '.join(clinical['reported_features'])+'. The node represents only the selected research cohort.',
              context={'cohort_scope':tier,'clinical_causality':'not independently adjudicated'})
        first=v['functional_evidence'][0]
        claim(vid,'AFFECTS','gene:'+gene,'paper:'+first['source_id'],first['evidence_location'],
              'Paraphrase: the tested receptor construct contains '+gene+' '+v['reported_protein']+'.',context={'identity_scope':'protein substitution; original DNA notation retained separately'})
        fn=v['integrated_function']
        effect='loss_of_function' if tier in {'core_likely_reduced','provisional_possible_reduced'} else 'gain_of_function' if tier=='opposing_control' else 'unknown'
        context={'effect':effect,'source_classification':fn['source_classification'],'cohort_tier':tier,
                 'species':'human recombinant receptor subunits','tissue':'heterologous expression systems',
                 'stage':'in vitro receptor characterization','assay_details':'; '.join(e['assay']+'; '+e['model'] for e in v['functional_evidence']),
                 'expert_review':'pending; machine_checked indicates source transcription only',
                 'scope_note':'Assay-level comparison only; neuronal, developmental and clinical transferability requires expert review.'}
        cid=claim(vid,'HAS_EFFECT',MECHANISM,'paper:'+fn['source_id'],fn['evidence_location'],
                  'Paraphrase: '+gene+' '+v['reported_protein']+' is categorized as '+fn['source_classification']+'. '+fn['why'],context=context,
                  review='unreviewed' if tier in {'provisional_possible_reduced','unresolved_control'} else 'machine_checked')
        for e in v['functional_evidence']:
            measures='; '.join(p['name']+' = '+str(p['variant'])+' '+p['unit']+' (n='+str(p['n'])+'); WT '+p['wt_control'] for p in e['measured_parameters'] if p['variant'] is not None)
            b['evidence'].append(dict(id=f'evidence:{len(b["evidence"])+1:03d}',claim_id=cid,source_id='paper:'+e['source_id'],locator=e['evidence_location'],
                excerpt='Tabulated measurements (structured factual transcription): '+measures,stance='supports',review_status='unreviewed' if tier=='provisional_possible_reduced' else 'machine_checked'))
    for (gene,tier),cohort in cohort_ids.items():
        b['coverage'].append(dict(id='coverage:'+slug(cohort),source_id='paper:myers2023',entity_id=cohort,scope='Selected variant classification and primary assay table checks',status='searched',searched_at=DATE,
            notes='Targeted ten-variant set; broader gene literature is harvested separately. No claim of all published functional variants or expert review.'))
    for r in resources['resources']:
        sid='resource-source:'+r['id']
        source(sid,r['name'],r['source_url'],kind='paper' if r['type']=='study_methods' else 'registry' if r['type']=='registry' else 'organization',published_at=r.get('published_at'))
        aid=node('asset:'+r['id'],'Asset',r['name'],asset_type=r['type'],access=r['access'],access_url=r['contact_url'],
                 reuse_scope=r['summary'],validation_questions=[r['reuse_question']]+r['limitations'],limitations=r['limitations'],availability='not independently confirmed',
                 research_question='Could existing registry measures and study methods support an observational comparison across selected GRIN2A and GRIN2B reduced-function variants?')
        for owner in r.get('maintainers',[]):
            oid=node('organization:'+slug(owner),'Organization',owner,contact_url=r['contact_url'],contact_scope='Public institutional or resource route; no contact sent')
            claim(oid,'MAINTAINS',aid,sid,r['locator'],'Paraphrase: '+r['name']+' is described as a resource of '+owner+'. Scope and current availability require confirmation.')
        for gene in ('GRIN2A','GRIN2B'):
            if gene not in r['genes']:continue
            cohort=cohort_ids[(gene,'core_likely_reduced')]
            provisional=r['type'] in {'biorepository','disease_model_program'}
            claim(aid,'RELEVANT_TO',cohort,sid,r['locator'],
                  'Paraphrase: '+r['summary']+' Potential adaptation to the selected cohort: '+r['reuse_question'],
                  context={'reported_scope':'gene-level resource description','selected_variant_inventory':'unknown','access_conditions':r['access'],'adaptation':'proposed research question, not established suitability'},
                  assertion='inferred' if provisional else 'reported')
    b['dataset']['curation_notes']=['Machine-checked source transcription is not expert scientific review.',
      'The existing GRIN connection and registry are acknowledged; the contribution is source-traceable research preparation.',
      'No treatments, trial eligibility or access permissions are inferred.',
      'S541G has a source cDNA/protein discrepancy and remains protein-level control evidence.']
    return b

def main():
    b=build()
    from atlas.model import validate_bundle
    errors=validate_bundle(b)
    if errors:raise ValueError(errors)
    atomic_json(OUTPUT,b)
    print(json.dumps({'output':str(OUTPUT),'nodes':len(b['nodes']),'claims':len(b['claims']),'evidence':len(b['evidence'])}))

if __name__=='__main__':main()
