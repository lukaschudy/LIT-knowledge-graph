"""Pinned, streaming rare-disease biology source acquisitions and normalization."""
from __future__ import annotations
import csv
import gzip
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from .core import download, emit_records, update_manifest, open_text, ROOT

HPO_VERSION = 'v2026-09-01'
MONDO_VERSION = 'v2026-09-01'
LICENSE_HPO = 'HPO terms of use: attribution, version/date display, preserve content and embedded logical relations'
LICENSE_CC = 'CC BY 4.0'
LICENSE_CLINVAR = 'NCBI ClinVar public data; retain attribution and third-party rights where applicable'
LICENSE_ORPHA = 'CC BY 4.0'


def obo_stanzas(path):
    """Yield OBO stanzas with every tag and repeated value preserved verbatim."""
    stanza_type = 'header'
    tags = {}
    def emit():
        return {'stanza_type': stanza_type, 'tags': tags}
    with open_text(path) as stream:
        for raw in stream:
            line = raw.rstrip('\r\n')
            if line.startswith('[') and line.endswith(']'):
                if stanza_type is not None:
                    yield emit()
                stanza_type, tags = line[1:-1], {}
            elif stanza_type is None:
                if line and not line.startswith('!') and ':' in line:
                    key, value = line.split(':', 1)
                    tags.setdefault(key, []).append(value.lstrip())
            elif line and not line.startswith('!') and ':' in line:
                key, value = line.split(':', 1)
                tags.setdefault(key, []).append(value.lstrip())
        if stanza_type is not None:
            yield emit()


def tsv_rows(path):
    with open_text(path) as stream:
        def rows():
            for line in stream:
                if not line.strip():
                    continue
                # ClinVar's header begins #AlleleID; HPO metadata comments
                # precede an unprefixed header. Preserve the actual header.
                if line.startswith('#'):
                    if '\t' in line:
                        yield line[1:]
                    continue
                yield line
        reader = csv.DictReader(rows(), delimiter='\t')
        if not reader.fieldnames:
            raise ValueError(f'Missing TSV header: {path}')
        for row in reader:
            yield dict(row)


def xml_node(element):
    """Loss-preserving recursive XML representation with attributes and repeats."""
    result = {'tag': element.tag, 'attributes': dict(element.attrib)}
    text = (element.text or '').strip()
    if text:
        result['text'] = text
    children = [xml_node(child) for child in list(element)]
    if children:
        result['children'] = children
    return result


def xml_records(path, element_local_name):
    for _event, element in ET.iterparse(path, events=('end',)):
        if element.tag.rsplit('}', 1)[-1] == element_local_name:
            yield xml_node(element)
            element.clear()


def xml_file_records(paths, element_local_name):
    """Emit each selected XML element with its containing product filename."""
    for path in paths:
        for record in xml_records(path, element_local_name):
            yield {'product_file': Path(path).name, 'record': record}


def owl_root_records(path):
    """Yield complete direct children of RDF root from OWL/XML RDF serialization."""
    stack = []
    for event, element in ET.iterparse(path, events=('start', 'end')):
        if event == 'start':
            stack.append(element)
        else:
            if len(stack) == 2:
                yield xml_node(element)
                element.clear()
            stack.pop()


def _fetch(source, filename, url, license_name, version):
    return download(source, url, filename, license_name=license_name, version=version)


def run_hpo():
    source='hpo'; version=HPO_VERSION; base=f'https://github.com/obophenotype/human-phenotype-ontology/releases/download/{version}'
    try:
        obo=_fetch(source,'hp-base.obo',base+'/hp-base.obo',LICENSE_HPO,version)
        hpoa=_fetch(source,'phenotype.hpoa',base+'/phenotype.hpoa',LICENSE_HPO,version)
        genes=_fetch(source,'genes_to_phenotype.txt',base+'/genes_to_phenotype.txt',LICENSE_HPO,version)
        gd=_fetch(source,'genes_to_disease.txt',base+'/genes_to_disease.txt',LICENSE_HPO,version)
        emit_records(source,'ontology_terms',obo_stanzas(obo),input_paths=(obo,),description='All OBO stanzas from pinned HPO hp-base.obo; all tags and repeated values retained.')
        emit_records(source,'disease_phenotype_annotations',tsv_rows(hpoa),input_paths=(hpoa,),description='All HPOA assertion columns retained, including NOT qualifiers, evidence, references, onset and frequency.')
        emit_records(source,'genes_to_phenotype',tsv_rows(genes),input_paths=(genes,),description='All rows/columns from official HPO genes_to_phenotype summary.')
        emit_records(source,'genes_to_disease',tsv_rows(gd),input_paths=(gd,),description='All rows/columns from official HPO genes_to_disease summary.')
        update_manifest(source,status='complete',scope='Complete pinned HPO OBO ontology, disease annotations, genes_to_phenotype and genes_to_disease files.',version=version)
    except Exception as e:
        update_manifest(source,status='failed',error=str(e),scope=f'Incomplete; intended complete pinned HPO assets, version {version}.')
        print(json.dumps({'event':'source_failed','source':source,'error':str(e)}),flush=True)


def run_mondo():
    source='mondo';version=MONDO_VERSION;base=f'https://github.com/monarch-initiative/mondo/releases/download/{version}'
    try:
        obo=_fetch(source,'mondo.obo',base+'/mondo.obo',LICENSE_CC,version)
        owl=_fetch(source,'mondo.owl',base+'/mondo.owl',LICENSE_CC,version)
        emit_records(source,'obo_stanzas',obo_stanzas(obo),input_paths=(obo,),description='All OBO stanzas and tags from complete pinned MONDO OBO; repeated fields, xrefs, synonyms, relations and obsolete/replacement metadata retained.')
        emit_records(source,'owl_axioms',owl_root_records(owl),input_paths=(owl,),description='Complete direct RDF/XML OWL root elements serialized recursively; captures ontology annotations, class axioms, equivalence, mappings, properties and provenance without flattening.')
        update_manifest(source,status='complete',scope='Complete pinned MONDO OWL and OBO.',version=version)
    except Exception as e:
        update_manifest(source,status='failed',error=str(e),scope=f'Incomplete; intended complete pinned MONDO OWL and OBO, version {version}.')
        print(json.dumps({'event':'source_failed','source':source,'error':str(e)}),flush=True)


def run_orphadata():
    source='orphadata'; products={
      'cross_references':('en_product1.xml','https://www.orphadata.com/data/xml/en_product1.xml','Disorder'),
      'phenotypes':('en_product4.xml','https://www.orphadata.com/data/xml/en_product4.xml','Disorder'),
      'genes':('en_product6.xml','https://www.orphadata.com/data/xml/en_product6.xml','Disorder'),
      'epidemiology':('en_product9_prev.xml','https://www.orphadata.com/data/xml/en_product9_prev.xml','Disorder'),
      'natural_history':('en_product9_ages.xml','https://www.orphadata.com/data/xml/en_product9_ages.xml','Disorder'),
    }
    completed=[]
    for name,(filename,url,tag) in products.items():
        try:
            path=_fetch(source,filename,url,LICENSE_ORPHA,'2026-07')
            emit_records(source,name,xml_records(path,tag),input_paths=(path,),description=f'All complete Disorder elements from Orphadata July 2026 {name} XML; recursive XML structure, attributes, text and repeated children retained.')
            completed.append(name)
        except Exception as e:
            update_manifest(source,status='partial',error=f'{name}: {e}',scope=f'Incomplete products {sorted(set(products)-set(completed))}; each product is recorded independently.')
            print(json.dumps({'event':'product_failed','source':source,'dataset':name,'error':str(e)}),flush=True)
    # Each July 2026 classification is a small official XML product. Retain
    # its filename on every row because the same disorder occurs in many trees.
    hchids=(146,147,148,150,152,156,181,182,183,184,185,186,187,188,189,193,194,
            195,196,197,198,199,200,201,202,203,204,205,209,212,216,231,233,235)
    try:
        class_paths=[]
        for hchid in hchids:
            filename=f'en_product3_{hchid}.xml'
            class_paths.append(_fetch(source,filename,f'https://www.orphadata.com/data/xml/{filename}',LICENSE_ORPHA,'2026-07'))
        emit_records(source,'classifications',xml_file_records(class_paths,'ClassificationNode'),input_paths=class_paths,
                     description='All 34 July 2026 Orphanet ClassificationNode records from official classification XML products, with source file, attributes, recursive structure, and repeated children preserved.')
        completed.append('classifications')
    except Exception as e:
        update_manifest(source,status='partial',error=f'classifications: {e}',scope='Partial Orphadata products; classification products incomplete.')
        print(json.dumps({'event':'product_failed','source':source,'dataset':'classifications','error':str(e)}),flush=True)
    expected=set(products)|{'classifications'}
    if len(completed)==len(expected):
        update_manifest(source,status='complete',scope='Complete July 2026 cross-reference, phenotype, associated-gene, epidemiology, natural-history and all 34 classification XML products. Other Orphadata products (such as linearisation, functional consequences, nomenclature packs and expert resources) are not included.')
    else:
        update_manifest(source,status='partial',scope=f'Completed products: {completed}; missing products: {sorted(expected-set(completed))}. Other Orphadata products (linearisation, functional consequences, nomenclature packs and expert resources) are not included.')


def run_clinvar():
    source='clinvar'; entries={
      'variant_summary':('variant_summary.txt.gz','https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz'),
      'gene_condition_source_id':('gene_condition_source_id','https://ftp.ncbi.nlm.nih.gov/pub/clinvar/gene_condition_source_id'),
    }
    completed=[]
    for name,(filename,url) in entries.items():
        try:
            path=_fetch(source,filename,url,LICENSE_CLINVAR,'current FTP snapshot (retrieval date in manifest)')
            records=tsv_rows(path)
            emit_records(source,name,records,input_paths=(path,),description=('Complete current FTP summary file, every column and row preserved verbatim. variant_summary represents all ClinVar variants with genomic locations but is summary-level only; it is not comprehensive assertion XML.' if name=='variant_summary' else 'Complete current daily gene-condition source-ID cross-reference file; every column and row preserved.'))
            completed.append(name)
        except Exception as e:
            update_manifest(source,status='partial',error=f'{name}: {e}',scope='Partial source products; comprehensive ClinVar VCV/RCV XML assertions were not acquired.')
            print(json.dumps({'event':'product_failed','source':source,'dataset':name,'error':str(e)}),flush=True)
    if len(completed)==len(entries):
        update_manifest(source,status='complete',scope='Complete variant_summary TSV (genome-located variants, summary metadata only) and gene_condition_source_id TSV. Comprehensive VCV/RCV/SCV assertion XML and variants without genomic location are excluded.')
    else:
        update_manifest(source,status='partial',scope=f'Completed products: {completed}; missing: {sorted(set(entries)-set(completed))}. Comprehensive VCV/RCV/SCV assertion XML is excluded.')


def main():
    for run in (run_hpo,run_mondo,run_orphadata,run_clinvar):
        run()

if __name__=='__main__':
    main()
