"""Preserve primary-paper table cells as source facts for curation verification."""
from html.parser import HTMLParser
from pathlib import Path
import json
from harvest.core import ROOT,RAW,emit_records,update_manifest

class Tables(HTMLParser):
    def __init__(self):
        super().__init__();self.rows=[];self.table=None;self.row=None;self.cell=None;self.table_number=0;self.row_number=0;self.cell_metadata=[];self.current_metadata=None
    def handle_starttag(self,tag,attrs):
        if tag=='table':
            self.table_number+=1;self.table=dict(attrs).get('id') or str(self.table_number);self.row_number=0
        elif tag=='tr' and self.table is not None:self.row=[];self.cell_metadata=[]
        elif tag in ('td','th') and self.row is not None:
            self.cell=[];a=dict(attrs);self.current_metadata={'rowspan':a.get('rowspan','1'),'colspan':a.get('colspan','1'),'images':[]}
        elif tag=='img' and self.cell is not None:
            a=dict(attrs);self.current_metadata['images'].append({k:a[k] for k in ('src','alt','id') if k in a})
        elif tag=='br' and self.cell is not None:self.cell.append(' ')
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()));self.cell_metadata.append(self.current_metadata);self.cell=None
        elif tag=='tr' and self.row is not None:
            self.row_number+=1;self.rows.append({'table_id':self.table,'table_number':self.table_number,'row_number':self.row_number,'cells':self.row,'cell_metadata':self.cell_metadata,'contains_untranscribed_images':any(c['images'] for c in self.cell_metadata)});self.row=None
        elif tag=='table':self.table=None

def run():
    evidence=json.loads((ROOT/'data/curated/grin_functional_evidence.json').read_text())
    paths=[];records=[]
    for source in evidence['sources']:
        path=RAW/'grin_primary_pages'/(source['pmcid']+'.html')
        p=Tables();p.feed(path.read_text());paths.append(path)
        if not p.rows:raise ValueError('No tables: '+str(path))
        records.extend(dict(source_id=source['source_id'],pmcid=source['pmcid'],source_url=source['url'],input_path=str(path.relative_to(ROOT)),**row) for row in p.rows)
    emit_records('grin_primary_tables','table_rows',records,input_paths=paths,description='HTML table text and cell image references from seven selected primary papers. Image-based values remain untranscribed and flagged; blank text does not establish missing data. Row/column spans preserved, not expanded.')
    update_manifest('grin_primary_tables',status='complete_for_scope',scope='Table text and image references present in seven selected primary article HTML pages; supplemental files and image transcription excluded',rows_with_untranscribed_images=sum(r['contains_untranscribed_images'] for r in records),limitations=['Cells containing images may encode measured values or classifications absent from the text. Use cell_metadata images and inspect the source; do not interpret a blank string as absent data.'])
if __name__=='__main__':run()
