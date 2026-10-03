"""Name MGI report fields from the provider index and embedded report headers."""
from harvest.core import RAW, download, emit_records, update_manifest

INDEX='https://www.informatics.jax.org/downloads/reports/index.html'
GENO='allelic_composition allele_symbols allele_ids genetic_background phenotype_id pubmed_ids marker_ids'
SCHEMAS={
 'HMD_HumanPhenotype':'human_symbol human_entrez_id mouse_symbol mouse_mgi_id phenotype_ids',
 'HOM_AllOrganism':'homology_class organism taxon_id symbol entrez_id mouse_mgi_id hgnc_id omim_id genetic_location genome_coordinates name synonyms',
 'MGI_PhenotypicAllele':'allele_id allele_symbol allele_name allele_type allele_attribute original_reference_pubmed_id marker_id marker_symbol marker_refseq_id marker_ensembl_id phenotype_ids synonyms marker_name',
 'MGI_Strain':'strain_id strain_name strain_type',
 'MGI_GenePheno':GENO+' genotype_id',
 'MGI_Geno_DiseaseDO':GENO+' disease_ids omim_ids genotype_id',
 'MGI_Geno_NotDiseaseDO':GENO+' disease_ids omim_ids genotype_id',
 'MGI_DiseaseGeneModel':'human_symbol human_gene_name hgnc_ids disease_name disease_id genotype_ids mouse_symbol mouse_mgi_id facilities repository_ids',
 'MGI_DiseaseMouseModel':'disease_name disease_id not_model allele_pairs strain_background allele_symbol allele_id allele_reference_count allele_repository_ids allele_rrids marker_symbol marker_id gene_repository_ids',
}

def rows(path,name):
    fields=SCHEMAS[name].split()
    with path.open() as handle:
        for line_number,line in enumerate(handle,1):
            if not line.strip() or line.startswith('#'):continue
            values=line.rstrip('\r\n').split('\t')
            if name=='HOM_AllOrganism' and values[0]=='DB Class Key':continue
            extra=values[len(fields):]
            # Provider adds trailing empty columns to HMD and no-model rows.
            # Retain them verbatim, but reject any unexplained nonempty field.
            if len(values)<len(fields) or any(extra):
                raise ValueError(f'{name} line {line_number}: schema mismatch ({len(values)} columns)')
            row=dict(zip(fields,values));row['native_columns']=values;row['source_line']=line_number
            row['schema_reference']=INDEX if name!='MGI_DiseaseMouseModel' else 'Embedded comment header in MGI_DiseaseMouseModel.rpt'
            if name in ('MGI_Geno_DiseaseDO','MGI_Geno_NotDiseaseDO'):
                row['qualifier']='NOT' if name=='MGI_Geno_NotDiseaseDO' else ''
            if name=='MGI_DiseaseMouseModel':
                row['qualifier']=row['not_model']
                row['has_mouse_model_record']=bool(row['allele_pairs'])
            yield row

def run():
    schema=download('mgi',INDEX,'report-index.html',license_name='MGI provider report-format documentation')
    counts={}
    for name in SCHEMAS:
        path=RAW/'mgi'/(name+'.rpt')
        emit_records('mgi',name.lower(),rows(path,name),input_paths=[path,schema],description='Provider-defined named fields plus all original positional columns and source line; embedded comment/header rows excluded. NOT model annotations remain explicit. No human disease/function inference from mouse annotations.')
    update_manifest('mgi',status='complete_for_scope',schema_reference=INDEX,scope='Nine acquired MGI reports, with native columns and provider-defined semantic field names',limitations=['MGI reports include non-rare conditions and multiple organisms where specified.','Mouse gene-level models and available stocks do not establish a human variant-specific phenotype or therapeutic effect.','Trailing empty columns are preserved in native_columns. Disease-only rows without allele pairs do not assert availability of a mouse model.'])

if __name__=='__main__':run()
