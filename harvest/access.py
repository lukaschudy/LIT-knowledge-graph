"""Record source-specific access gaps without pretending missing data is empty."""
from harvest.core import update_manifest,manifest,atomic_json,ROOT
GAPS={
 'omim':('permission_required','Registered/licensed bulk/API access not supplied. Imported OMIM identifiers in other sources do not substitute for OMIM content.','https://omim.org/'),
 'nord':('permission_required','Provider offers a gated disease CSV request; terms restrict extraction/reuse without permission. No request submitted.','https://rarediseases.org/request-rdb-access/'),
 'global_genes':('permission_required','Current member-list and historical PDF route returned HTTP 403 during source research; terms restrict automated content extraction. No bypass attempted.','https://globalgenes.org/about-us/global-advocacy-alliance/global-advocacy-alliance-members/'),
 'eurordis':('access_blocked','Directory returned HTTP 429 in source research and again in this harvest; no bulk export or reuse grant confirmed.','https://www.eurordis.org/who-we-are/our-members/'),
 'genetic_alliance_us':('provider_export_needed','Disease InfoSearch public UI returned no records in research; no documented export/API or suitable bulk-use grant established. This is not evidence the directory is empty.','https://geneticalliance.org/disease-info-search'),
 'rareconnect':('retired_metadata_only','Platform retired 5 December 2023. No patient posts, profiles or health narratives collected; archive metadata access/export not established.','https://www.rareconnect.org/en/announcements'),
 'orphanet_expert_resources':('permission_required','Open Orphadata scientific products acquired separately. Expert-resource/patient-organization data require separate access and licensing.','https://www.orphadata.com/'),
}
MAP={
 'S01':['omim'],'S02':['clinvar'],'S03':['hpo'],'S04':['pubmed','europe_pmc_diseases','grin_literature'],
 'S05':['pmc_grin_oa'],'S06':['clinicaltrials_gov'],'S07':['nih_reporter'],'S08':['nord'],'S09':['global_genes'],
 'S10':['orphadata','orphanet_expert_resources'],'S11':['grin_resources'],'S12':['eurordis'],
 'S13':['genetic_alliance_uk'],'S14':['genetic_alliance_us'],'S15':['mondo'],'S16':['grin_resources'],
 'S17':['mgi'],'S18':['rareconnect'],'S19':['europe_pmc_preprints'],'S20':['europe_pmc_preprints'],'S21':['raresource'],
}
def run():
    for source,(status,reason,url) in GAPS.items():
        if manifest(source).get('datasets'):continue
        update_manifest(source,status=status,scope='Source content not acquired',reason=reason,provider_url=url,evidence_notes='docs/research/'+('biology.md' if source in ('omim','orphanet_expert_resources') else 'assets.md' if source=='rareconnect' else 'community.md'))
    atomic_json(ROOT/'data/harvest-source-map.json',{'pdf_sources':MAP,'notes':['S13 is Rare Disease UK, a campaign operated by Genetic Alliance UK; acquired member-directory records are explicitly the GAUK directory.','S19/S20 preprints are indexed Europe PMC PPR query results, not guaranteed complete bioRxiv/medRxiv server dumps.','S11/S16 are unbounded source classes, scoped to verified GRIN resources and announcements for the demonstration.','No original PDF source is silently omitted; missing access and incomplete scope remain visible.']})
if __name__=='__main__':run()
