import gzip
from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

@unittest.skipUnless(importlib.util.find_spec('indexed_gzip'), 'install the graph extra for gzip indexing tests')
class HarvestBuildTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.database=self.root/'graph.sqlite'
        self.rows=[{'GENE SYMBOL':'EPG5','GENE ID (HGNC)':'HGNC:29331','DISEASE LABEL':'Vici syndrome',
                    'DISEASE ID (MONDO)':'MONDO:0010282','CLASSIFICATION':'Definitive'},
                   {'GENE SYMBOL':'WDR45','GENE ID (HGNC)':'HGNC:28912','DISEASE LABEL':'BPAN',
                    'DISEASE ID (MONDO)':'MONDO:0018955','CLASSIFICATION':'Limited'}]
        self.add_dataset('clingen','gene_disease_validity',self.rows)
        self.add_dataset('unknown','native',[{'unmapped_metadata':'all fields must remain retrievable'}])
    def add_dataset(self,source,name,rows):
        path=self.root/f'data/processed/harvest/{source}/{name}.jsonl.gz';path.parent.mkdir(parents=True,exist_ok=True)
        with gzip.open(path,'wt') as f:
            for row in rows:f.write(json.dumps(row)+'\n')
        manifest={'artifacts':{'fixture':{'url':'https://example.org/fixture','license':'fixture'}},
                  'datasets':{name:{'path':str(path.relative_to(self.root)),'sha256':sha256(path.read_bytes()).hexdigest(),
                              'records':len(rows),'bytes':path.stat().st_size}}}
        dest=self.root/f'data/harvest-manifests/{source}.json';dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(json.dumps(manifest))
    def test_all_rows_roundtrip_and_resume_does_not_duplicate_edges(self):
        from atlas.harvest_graph.build import build
        from atlas.harvest_graph.source_reader import read_record
        stats=build(self.root,self.database,batch_size=1,reserve_bytes=0)
        self.assertEqual(stats['status'],'complete');self.assertEqual(stats['processed_records'],3)
        with sqlite3.connect(self.database) as db:
            count=db.execute('select count(*) from edges').fetchone()[0]
            did,path,metadata=db.execute("select id,path,metadata from datasets where key='unknown/native'").fetchone()
        original=read_record(self.database,self.root,{'dataset_id':did,'path':path,'row':1,'metadata':json.loads(metadata)})
        self.assertEqual(original['data'],{'unmapped_metadata':'all fields must remain retrievable'})
        resumed=build(self.root,self.database,batch_size=1,reserve_bytes=0)
        self.assertEqual(resumed['total_edges'],count)
        self.assertEqual(resumed['processed_records'],3)
    def test_changed_source_fails_before_its_rows_are_published(self):
        from atlas.harvest_graph.build import build
        path=next((self.root/'data/processed/harvest/clingen').glob('*.gz'))
        payload=bytearray(path.read_bytes());payload[-1]^=1;path.write_bytes(payload)
        with self.assertRaisesRegex(ValueError,'checksum'):
            build(self.root,self.database,reserve_bytes=0)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute('select count(*) from nodes').fetchone()[0],0)
    def test_checkpoint_resume_preserves_row_pointer_alignment(self):
        from atlas.harvest_graph.build import build
        interrupted=[False]
        def stop(stats):
            if stats['processed_records']==1 and not interrupted[0]:
                interrupted[0]=True;raise RuntimeError('Simulated interruption')
        with self.assertRaisesRegex(RuntimeError,'Simulated'):
            build(self.root,self.database,batch_size=1,reserve_bytes=0,progress=stop)
        result=build(self.root,self.database,batch_size=1,reserve_bytes=0)
        self.assertEqual(result['processed_records'],3)
        with sqlite3.connect(self.database) as db:
            rows=db.execute('select id,processed_rows from datasets').fetchall()
        for did,count in rows:self.assertEqual(Path(str(self.database)+f'.sources/{did}.offsets').stat().st_size,count*8)

    def test_cached_placeholder_label_is_upgraded_in_later_batch(self):
        from unittest.mock import patch
        from atlas.harvest_graph.build import build
        def mapping(source,dataset,row):
            if source != 'clingen': return [],[]
            node={'id':'Test:shared','type':'Gene','label':'Test:shared' if row['GENE SYMBOL']=='EPG5' else 'Readable gene'}
            return [node],[]
        with patch('atlas.harvest_graph.build.adapt',mapping):
            build(self.root,self.database,batch_size=1,reserve_bytes=0)
        with sqlite3.connect(self.database) as db:
            self.assertEqual(db.execute("select label from nodes where id='Test:shared'").fetchone()[0],'Readable gene')
