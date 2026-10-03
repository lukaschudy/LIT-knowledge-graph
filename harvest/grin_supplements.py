"""Archive and extract the selected classification paper's supplemental PDF."""
import subprocess, zipfile
from harvest.core import ROOT, RAW, download, digest, emit_records, update_manifest

def run():
    source='grin_supplements'
    path=download(source,'https://www.ebi.ac.uk/europepmc/webservices/rest/PMC10508039/supplementaryFiles','myers2023-supplementaryFiles.zip',license_name='CC BY 4.0, as stated in PMC10508039 article copyright notice')
    member='supplemental_information_8-7-23_final6_ddad104.pdf'
    with zipfile.ZipFile(path) as archive:
        payload=archive.read(member)
    if not payload.startswith(b'%PDF'):raise ValueError('Supplement is not a PDF')
    pdf=RAW/source/member;pdf.write_bytes(payload)
    text_path=RAW/source/'myers2023-supplement.txt'
    subprocess.run(['pdftotext','-layout',str(pdf),str(text_path)],check=True)
    pages=text_path.read_text().split('\f')
    if not pages[-1].strip():pages.pop()
    emit_records(source,'myers2023_supplement_pages',({'source_id':'myers2023','pmcid':'PMC10508039','zip_member':member,'pdf_sha256':digest(pdf),'page':i,'layout_text':s} for i,s in enumerate(pages,1)),input_paths=[path],description='Per-page pdftotext -layout extraction of supplemental Tables S1–S5 and methods. Native PDF preserved; table interpretation and OCR of graphics are separate review work.')
    update_manifest(source,status='complete_for_scope',scope='Myers 2023 supplemental PDF from Europe PMC supplementaryFiles; other papers supplements not included',derived_files=[{'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':digest(p),'input_path':str(path.relative_to(ROOT))} for p in [pdf,text_path]],invalid_research_artifacts={'myers2023-supplement.pdf':'Direct PMC endpoint returned HTML access page, not a PDF; not parsed or used as evidence.'},limitations=['Layout text is not a semantic table reconstruction. Color, figure labels and embedded images may require manual inspection.','Supplemental coverage is one selected paper, not all acquired literature.'])

if __name__=='__main__':run()
