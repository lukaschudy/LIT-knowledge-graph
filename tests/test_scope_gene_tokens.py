import unittest
from atlas.demo_scope import mentioned_external_genes


class ProteinNotationScopeTests(unittest.TestCase):
    def test_protein_prefix_is_not_an_external_gene(self):
        nodes = [{'id': 'outside:p', 'label': 'P', 'type': 'Gene'},
                 {'id': 'outside:arx', 'label': 'ARX', 'type': 'Gene'}]
        for variant in ['p.Ser541Arg', 'p.S541R', 'p.(Ser541Arg)', 'p.ser541arg']:
            with self.subTest(variant=variant):
                self.assertEqual(mentioned_external_genes('Explain GRIN2B ' + variant, nodes, set()), [])
                outside = mentioned_external_genes('Compare ARX and GRIN2B ' + variant, nodes, set())
                self.assertEqual([n['label'] for n in outside], ['ARX'])
        self.assertEqual([n['label'] for n in mentioned_external_genes('Compare P and GRIN2B', nodes, set())], ['P'])
