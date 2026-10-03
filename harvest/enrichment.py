"""Open enrichment harvesters. Native fields and evidence are preserved."""
from __future__ import annotations
import csv, gzip, io, json, re, sys, traceback, zipfile
from pathlib import Path
from urllib.parse import urljoin
import requests
from harvest.core import download, emit_records, update_manifest, open_text, manifest, atomic_json, MANIFESTS

LICENSES = {
 'hgnc':'HGNC data use unrestricted; attribution retained', 'reactome':'Reactome license; attribution required',
 'clingen':'ClinGen source terms; see provider download page', 'gencc':'CC0 1.0; attribution requested',
 'uniprot':'CC BY 4.0', 'go':'See release-specific ontology/annotation license',
 'mgi':'CC BY 4.0 for data and annotations', 'ror':'CC0 1.0',
}
SCOPE = {
 'hgnc':'Current complete approved HGNC gene dataset plus complete withdrawn symbol report.',
 'reactome':'Current complete pathway, hierarchy and UniProt mapping files; mapping contains all organisms (organism retained; human subset is filterable).',
 'clingen':'Complete current Gene-Disease Validity (standard and lumping/splitting), Gene Dosage and all Gene Dosage CSV exports.',
 'gencc':'Current complete versioned SGC assertion CSV export (new format).',
 'uniprot':'All reviewed UniProtKB human (taxon 9606) records returned by current release stream.',
 'go':'Current go-basic ontology and complete GOA human GAF annotation file.',
 'mgi':'Complete official orthology, human phenotype, allele, strain, gene phenotype and disease-model reports. Only positional native report columns emitted; semantic schemas not verified.',
 'ror':'Current complete versioned ROR data dump ZIP, including inactive and withdrawn organizations.',
}

def delimited(path, delimiter='\t'):
    with open_text(path) as f:
        yield from csv.DictReader(f, delimiter=delimiter)

def rows_with_columns(path, columns):
    with open_text(path) as f:
        for line in f:
            if not line.strip(): continue
            yield dict(zip(columns,line.rstrip('\r\n').split('\t')))

def clingen_rows(path):
    with open_text(path) as f:
        for _ in range(4): next(f)
        reader=csv.DictReader(f)
        next(reader, None)  # separator row of plus signs
        yield from reader

def json_records(path, key=None):
    with open_text(path) as f:
        obj=json.load(f)
    if key:
        yield from obj[key]
    elif isinstance(obj,list):
        yield from obj
    else:
        yield obj

def gaf_records(path):
    """GAF 2.x fixed columns, preserving all native values including NOT qualifiers."""
    with open_text(path) as f:
        for line in f:
            if not line.strip() or line.startswith('!'): continue
            c=line.rstrip('\n').split('\t')
            if len(c)<17: continue
            yield dict(zip(('db','db_object_id','db_object_symbol','qualifier','go_id','reference','evidence_code','with_from','aspect','db_object_name','db_object_synonym','db_object_type','taxon','date','assigned_by','annotation_extension','gene_product_form_id'),c[:17]))

def mgi_rows(path, names):
    for row in delimited(path):
        yield dict(zip(names, row.values()))

def run_one(name, fn):
    try:
        fn()
        data=manifest(name);data.pop('failure',None)
        atomic_json(MANIFESTS/(name+'.json'),data)
        update_manifest(name,status='complete',rights=LICENSES[name],coverage=SCOPE[name],limitations='Provider file is a mutable current-release endpoint; exact retrieval timestamp and SHA-256 are recorded per artifact. Native evidence and provenance fields are retained wherever supplied.')
    except Exception as e:
        update_manifest(name,status='failed',failure={'error':str(e),'type':type(e).__name__},rights=LICENSES.get(name,'unknown'))
        print(json.dumps({'event':'source_failed','source':name,'error':str(e)}),flush=True)

def fetch(source,url,file,version=None):
    return download(source,url,file,license_name=LICENSES[source],version=version)

def hgnc():
    base='https://storage.googleapis.com/public-download-files/hgnc/tsv/tsv/'
    for fn in ('hgnc_complete_set.txt','withdrawn.txt'):
        p=fetch('hgnc',base+fn,fn)
        emit_records('hgnc',fn.removesuffix('.txt'),delimited(p),input_paths=[p],description='Complete current HGNC TSV; all native columns retained.')

def reactome():
    base='https://reactome.org/download/current/'
    files=['UniProt2Reactome_All_Levels.txt','ReactomePathways.txt','ReactomePathwaysRelation.txt']
    for fn in files:
        p=fetch('reactome',base+fn,fn)
        columns={'UniProt2Reactome_All_Levels.txt':['uniprot_accession','reactome_pathway_id','pathway_url','pathway_name','evidence_code','species'], 'ReactomePathways.txt':['reactome_pathway_id','pathway_name','species'], 'ReactomePathwaysRelation.txt':['parent_pathway_id','child_pathway_id']}[fn]
        emit_records('reactome',fn.removesuffix('.txt'),rows_with_columns(p,columns),input_paths=[p],description='Complete headerless Reactome release file; columns labeled from official file specification, full organism/evidence retained.')

def clingen():
    for fn,url in [('gene_disease_validity.csv','https://search.clinicalgenome.org/kb/gene-validity/download'),('gene_disease_validity_lumping_splitting.csv','https://search.clinicalgenome.org/kb/gene-validity/download/ls'),('gene_dosage.csv','https://search.clinicalgenome.org/kb/gene-dosage/download'),('gene_dosage_all.csv','https://search.clinicalgenome.org/kb/gene-dosage/downloadall')]:
        p=fetch('clingen',url,fn)
        emit_records('clingen',fn.removesuffix('.csv'),clingen_rows(p),input_paths=[p],description='Complete official ClinGen CSV export; metadata and separator rows excluded, native labeled columns retained.')

def gencc():
    # Current official export provides stable, versioned submission identifiers.
    url='https://thegencc.org/download/action/submissions-export-csv?format=new'
    p=fetch('gencc',url,'assertions.csv')
    emit_records('gencc','assertions',delimited(p,','),input_paths=[p],description='Complete GenCC CSV export; all source assertions retained.')

def uniprot():
    url='https://rest.uniprot.org/uniprotkb/stream?query=(reviewed:true)%20AND%20(organism_id:9606)&format=json&compressed=true'
    p=fetch('uniprot',url,'reviewed_human.json.gz')
    def records():
        with gzip.open(p,'rt',encoding='utf-8') as f:
            obj=json.load(f)
        yield from obj.get('results',obj) if isinstance(obj,dict) else obj
    emit_records('uniprot','reviewed_human',records(),input_paths=[p],description='Complete reviewed human UniProtKB records from stream API, with native JSON objects and evidence retained.')

def go():
    for name,url in [('go-basic.obo','https://current.geneontology.org/ontology/go-basic.obo'),('goa_human.gaf.gz','https://current.geneontology.org/annotations/goa_human.gaf.gz')]:
        p=fetch('go',url,name)
        if name.endswith('.obo'):
            def obo():
                term={}
                with open_text(p) as f:
                    for line in f:
                        line=line.rstrip('\n')
                        if line=='[Term]':
                            if term: yield term
                            term={'type':'Term'}
                        elif line.startswith('['):
                            if term: yield term
                            term={'type':line.strip('[]')}
                        elif ': ' in line and term:
                            k,v=line.split(': ',1);term.setdefault(k,[]).append(v)
                    if term: yield term
            emit_records('go','ontology',obo(),input_paths=[p],description='Complete GO basic ontology, stanza fields preserved.')
        else:
            emit_records('go','human_annotations',gaf_records(p),input_paths=[p],description='Complete GOA human GAF 2.x, preserving evidence, qualifier, references, extensions and taxon.')

def mgi():
    base='https://www.informatics.jax.org/downloads/reports/'
    specs=['HMD_HumanPhenotype.rpt','HOM_AllOrganism.rpt','MGI_PhenotypicAllele.rpt','MGI_Strain.rpt',
           'MGI_GenePheno.rpt','MGI_Geno_DiseaseDO.rpt','MGI_Geno_NotDiseaseDO.rpt',
           'MGI_DiseaseGeneModel.rpt','MGI_DiseaseMouseModel.rpt']
    for fn in specs:
        p=fetch('mgi',base+fn,fn)
        def records(p=p):
            with open_text(p) as f:
                for line in f:
                    if not line.strip() or line.startswith('#'):continue
                    cols=line.rstrip('\r\n').split('\t')
                    yield {'native_columns':cols}
        emit_records('mgi',fn.removesuffix('.rpt').lower(),records(),input_paths=[p],description='Complete MGI tab-delimited report; original positional columns retained without unverified semantic labels.')

def ror():
    # Resolve the latest versioned ROR record from Zenodo's official API.
    api='https://zenodo.org/api/records/?q=communities:ror-data&sort=mostrecent&size=1'
    j=requests.get(api,timeout=40).json(); hits=j.get('hits',{}).get('hits',[])
    if not hits: raise RuntimeError('No ROR data dump record found from Zenodo API')
    hit=hits[0]; files=hit.get('files',[])
    chosen=next((x for x in files if x['key'].lower().endswith('.zip') and 'ror-data' in x['key'].lower()),None)
    if not chosen: raise RuntimeError('Latest ROR Zenodo record has no data ZIP')
    p=fetch('ror',chosen['links']['self'],'ror-data.zip',version=str(hit.get('id')))
    def records():
        with zipfile.ZipFile(p) as archive:
            names=[n for n in archive.namelist() if n.lower().endswith('.json')]
            if len(names)!=1: raise RuntimeError(f'Expected one JSON file in ROR ZIP, found {names}')
            with archive.open(names[0]) as f:
                obj=json.load(f)
            yield from obj
    emit_records('ror','organizations',records(),input_paths=[p],description='Complete versioned ROR JSON data dump including inactive and withdrawn records.')

def main():
    jobs=[('hgnc',hgnc),('reactome',reactome),('clingen',clingen),('gencc',gencc),('uniprot',uniprot),('go',go),('mgi',mgi),('ror',ror)]
    for name,fn in jobs: print(json.dumps({'event':'source_started','source':name}),flush=True);run_one(name,fn)

if __name__=='__main__': main()
