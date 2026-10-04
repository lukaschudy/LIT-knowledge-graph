"""The proposal queue is isolated, validated and safely retryable."""
import json
import sqlite3
import unittest
import uuid
from pathlib import Path
from atlas.proposals import SCHEMA, INDEX, ProposalError, submit_proposal, proposal_status
from atlas.cluster_questions import answer_cluster_question

class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.execute(SCHEMA); self.db.execute(INDEX)
        self.data = dict(request_id=str(uuid.uuid4()), query='missing item', name='Missing paper', kind='paper', description='A published source to review.', source_url='https://doi.org/10.123/example', entry='search')

    def tearDown(self): self.db.close()

    def execute(self, sql, *args): return [dict(r) for r in self.db.execute(sql, args).fetchall()]

    def test_retry_returns_same_receipt_and_preserves_private_payload(self):
        status, first = submit_proposal(self.data, self.execute, now=1000)
        second_status, second = submit_proposal(self.data, self.execute, now=2000)
        self.assertEqual((status,second_status),(201,200)); self.assertEqual(first,second)
        self.assertEqual(proposal_status(first['id'],self.execute), first)
        self.assertNotIn('payload', first)
        self.assertEqual(self.execute('SELECT COUNT(*) AS n FROM proposals')[0]['n'],1)
        payload=json.loads(self.execute('SELECT payload FROM proposals')[0]['payload'])
        self.assertEqual(payload['description'], self.data['description'])
        self.assertEqual(first['status'],'pending_review')

    def test_cannot_reuse_id_for_different_content(self):
        submit_proposal(self.data,self.execute)
        with self.assertRaises(ProposalError) as error:
            submit_proposal({**self.data,'name':'Changed'},self.execute)
        self.assertEqual(error.exception.status,409)

    def test_cannot_set_reviewed_status_or_inject_sql(self):
        self.data.update(name="'); DROP TABLE proposals;--",status='approved')
        _, receipt = submit_proposal(self.data,self.execute)
        self.assertEqual(receipt['status'],'pending_review')
        self.assertEqual(self.execute('SELECT COUNT(*) AS n FROM proposals')[0]['n'],1)

    def test_invalid_fields_and_unsafe_sources(self):
        for field,value in [('source_url','javascript:alert(1)'),('source_url','https://user:password@example.com'),('source_url','https://x:bad'),('name',''),('name','a'*161),('description','short'),('kind','approved'),('entry','invented'),('request_id','x'*36),('query',{'x':1})]:
            with self.subTest(field=field,value=value),self.assertRaises(ProposalError):
                submit_proposal({**self.data,field:value},self.execute)
        self.assertEqual(self.execute('SELECT COUNT(*) AS n FROM proposals')[0]['n'],0)

    def test_rate_limit_does_not_block_idempotent_retry(self):
        for _ in range(120):
            self.data['request_id']=str(uuid.uuid4());submit_proposal(self.data,self.execute,now=1000)
        self.assertEqual(submit_proposal(self.data,self.execute,now=1001)[0],200)
        self.data['request_id']=str(uuid.uuid4())
        with self.assertRaises(ProposalError) as error:submit_proposal(self.data,self.execute,now=1001)
        self.assertEqual(error.exception.status,429)
        self.assertEqual(submit_proposal(self.data,self.execute,now=4601)[0],201)

    def test_unknown_receipts(self):
        for identifier in ['bad',str(uuid.uuid4())]:
            with self.assertRaises(ProposalError) as error:proposal_status(identifier,self.execute)
            self.assertEqual(error.exception.status,404)

class CoverageGapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cluster=json.loads(Path('data/curated/grin_cluster_demo_v2.json').read_text())

    def test_unknown_variant_does_not_fall_back_to_selected_context(self):
        for q in ['What evidence for GRIN2B p.Arg999Gln?', 'Compare GRIN2B S541R and R999Q', 'Show GRIN2A S541R']:
            result=answer_cluster_question(self.cluster,q,self.cluster['members'][0]['id'])
            self.assertIn('coverage gap',result['answer']);self.assertEqual(result['proposal']['query'],q)
            self.assertEqual(result['node_ids'],[])

    def test_known_and_clinical_do_not_offer_gap_submission(self):
        self.assertNotIn('proposal',answer_cluster_question(self.cluster,'Explain GRIN2B S541R'))
        self.assertIsNone(answer_cluster_question(self.cluster,'What treatment for GRIN2B R999Q?'))
