import random
import unittest

from atlas.resolution import resolve_entities


class EntityResolutionTests(unittest.TestCase):
    def test_real_identifier_wins_over_source_node_with_identifier_property(self):
        nodes = [
            {'id':'a:source','type':'Gene','label':'Source','properties':{'hgnc_id':'HGNC:1'}},
            {'id':'HGNC:1','type':'Gene','label':'Registry','properties':{}},
        ]
        result=resolve_entities(nodes,[{'subject':'a:source','object':'HGNC:1','rule':'registry_same_as','provenance':{'row':1}}])
        self.assertEqual(result['alias_map']['a:source'],'HGNC:1')

    def test_doi_parenthesis_is_identity_content(self):
        nodes=[{'id':identifier,'type':'Publication','label':'Paper'} for identifier in ['DOI:10.1000/abc','DOI:10.1000/abc)']]
        result=resolve_entities(nodes,[{'subject':nodes[0]['id'],'object':nodes[1]['id'],'rule':'publication_identifiers','provenance':{'row':1}}])
        self.assertEqual(len(result['nodes']),2)
        self.assertEqual(result['decisions'][0]['status'],'rejected_identity_conflict')

    def test_labels_and_source_scoped_mentions_never_merge_without_identity_links(self):
        nodes = [
            {'id': 'mention:paper-a:1', 'type': 'Gene', 'label': 'WDR45', 'aliases': [], 'properties': {}},
            {'id': 'mention:paper-b:7', 'type': 'Gene', 'label': 'WDR45', 'aliases': [], 'properties': {}},
            {'id': 'gene:homonym', 'type': 'Gene', 'label': 'AP4B1', 'aliases': [], 'properties': {}},
            {'id': 'asset:homonym', 'type': 'Asset', 'label': 'AP4B1', 'aliases': [], 'properties': {}},
        ]
        result = resolve_entities(nodes, [])
        self.assertEqual(len(result['nodes']), 4)
        self.assertEqual(result['alias_map']['mention:paper-a:1'], 'mention:paper-a:1')
        self.assertEqual(result['alias_map']['mention:paper-b:7'], 'mention:paper-b:7')

    def test_trusted_links_merge_only_same_type_and_choose_registry_canonical(self):
        nodes = [
            {'id': 'source:gene:1', 'type': 'Gene', 'label': 'WD repeat domain 45', 'aliases': [],
             'properties': {'provenance': {'source': 'paper'}}},
            {'id': 'HGNC:28912', 'type': 'Gene', 'label': 'WDR45', 'aliases': ['WIPI4'],
             'properties': {'provenance': {'source': 'registry'}}},
            {'id': 'MONDO:0018955', 'type': 'Disease', 'label': 'BPAN', 'aliases': [], 'properties': {}},
        ]
        links = [{'subject': 'source:gene:1', 'object': 'HGNC:28912', 'rule': 'registry_same_as',
                  'provenance': {'source_id': 'source:hgnc'}}]
        result = resolve_entities(nodes, links)
        self.assertEqual(len(result['nodes']), 2)
        gene = next(node for node in result['nodes'] if node['type'] == 'Gene')
        self.assertEqual(gene['id'], 'HGNC:28912')
        self.assertEqual(gene['aliases'], ['WD repeat domain 45', 'WIPI4'])
        identity = gene['properties']['identity_resolution']
        self.assertEqual(identity['member_ids'], ['HGNC:28912', 'source:gene:1'])
        self.assertEqual(len(identity['node_provenance']), 2)
        self.assertEqual(identity['link_provenance'][0]['provenance'], {'source_id': 'source:hgnc'})
        self.assertEqual(result['decisions'][0]['status'], 'merged')

    def test_transitive_authoritative_conflict_is_visible_and_does_not_union(self):
        nodes = [
            {'id': 'HGNC:1', 'type': 'Gene', 'label': 'Gene A', 'aliases': [], 'properties': {}},
            {'id': 'source:bridge', 'type': 'Gene', 'label': 'Gene A', 'aliases': [], 'properties': {}},
            {'id': 'HGNC:2', 'type': 'Gene', 'label': 'Gene A', 'aliases': [], 'properties': {}},
        ]
        links = [
            {'subject': 'HGNC:1', 'object': 'source:bridge', 'rule': 'registry_same_as', 'provenance': {'row': 1}},
            {'subject': 'source:bridge', 'object': 'HGNC:2', 'rule': 'curated_identifier', 'provenance': {'row': 2}},
        ]
        result = resolve_entities(nodes, links)
        self.assertEqual(len(result['nodes']), 2)
        rejected = next(row for row in result['decisions'] if row['status'] == 'rejected_identity_conflict')
        self.assertEqual(rejected['conflict'], [{'namespace': 'HGNC', 'identifiers': ['1', '2']}])
        self.assertTrue(any(row['kind'] == 'link_identity_conflict' for row in result['conflicts']))

    def test_clinvar_identifiers_keep_distinct_variants_even_with_same_label(self):
        nodes = [
            {'id': 'ClinVar:12345', 'type': 'Variant', 'label': 'WDR45 c.1A>G', 'aliases': [], 'properties': {}},
            {'id': 'ClinVar:67890', 'type': 'Variant', 'label': 'WDR45 c.1A>G', 'aliases': [], 'properties': {}},
        ]
        result = resolve_entities(nodes, [
            {'subject': nodes[0]['id'], 'object': nodes[1]['id'], 'rule': 'registry_same_as', 'provenance': {'source': 'bad mapping'}}
        ])
        self.assertEqual(len(result['nodes']), 2)
        self.assertEqual(result['decisions'][0]['status'], 'rejected_identity_conflict')

    def test_publication_identity_canonical_priority_and_conflicting_authorities(self):
        nodes = [
            {'id': 'doi:10.1000/ABC', 'type': 'Publication', 'label': 'Study', 'aliases': [], 'properties': {}},
            {'id': 'PMID:123456', 'type': 'Publication', 'label': 'Study', 'aliases': [], 'properties': {}},
        ]
        result = resolve_entities(nodes, [
            {'subject': nodes[0]['id'], 'object': nodes[1]['id'], 'rule': 'publication_identifiers', 'provenance': {'source': 'PubMed'}}
        ])
        self.assertEqual(result['nodes'][0]['id'], 'PMID:123456')
        self.assertEqual(result['alias_map']['doi:10.1000/ABC'], 'PMID:123456')
        # Distinct PMIDs can never collapse through a DOI bridge.
        nodes.append({'id': 'PMID:222', 'type': 'Publication', 'label': 'Other', 'aliases': [], 'properties': {}})
        links = [
            {'subject': 'doi:10.1000/ABC', 'object': 'PMID:123456', 'rule': 'publication_identifiers', 'provenance': {'source': 'PubMed'}},
            {'subject': 'doi:10.1000/ABC', 'object': 'PMID:222', 'rule': 'publication_identifiers', 'provenance': {'source': 'PubMed'}},
        ]
        conflicted = resolve_entities(nodes, links)
        self.assertEqual(len(conflicted['nodes']), 2)
        self.assertTrue(any(row['status'] == 'rejected_identity_conflict' for row in conflicted['decisions']))

    def test_rule_type_missing_node_and_self_links_are_reported(self):
        nodes = [{'id': 'HGNC:7', 'type': 'Gene', 'label': 'G', 'aliases': [], 'properties': {}}]
        links = [
            {'subject': 'HGNC:7', 'object': 'missing', 'rule': 'registry_same_as', 'provenance': {'source_id': 'source:table'}},
            {'subject': 'HGNC:7', 'object': 'HGNC:7', 'rule': 'fuzzy_label', 'provenance': {}},
            {'subject': 'HGNC:7', 'object': 'HGNC:7', 'rule': 'curated_identifier', 'provenance': {'source_id': 'source:table'}},
        ]
        statuses = [item['status'] for item in resolve_entities(nodes, links)['decisions']]
        self.assertCountEqual(statuses, ['rejected_missing_node', 'rejected_untrusted_rule', 'already_connected'])

    def test_identity_link_without_provenance_cannot_merge(self):
        nodes = [
            {'id': 'HGNC:10', 'type': 'Gene', 'label': 'A', 'aliases': [], 'properties': {}},
            {'id': 'source:10', 'type': 'Gene', 'label': 'A', 'aliases': [], 'properties': {}},
        ]
        result = resolve_entities(nodes, [
            {'subject': nodes[0]['id'], 'object': nodes[1]['id'], 'rule': 'registry_same_as', 'provenance': {}}
        ])
        self.assertEqual(len(result['nodes']), 2)
        self.assertEqual(result['decisions'][0]['status'], 'rejected_missing_provenance')

    def test_malformed_provenance_never_authorizes_an_identity_merge(self):
        nodes = [{'id': identifier, 'type': 'Gene', 'label': 'A'} for identifier in ('HGNC:10', 'source:10')]
        for provenance in (False, True, 0, 1, '   ', None, [], {}):
            with self.subTest(provenance=provenance):
                result = resolve_entities(nodes, [{'subject': 'HGNC:10', 'object': 'source:10',
                    'rule': 'registry_same_as', 'provenance': provenance}])
                self.assertEqual(len(result['nodes']), 2)
                self.assertEqual(result['decisions'][0]['status'], 'rejected_missing_provenance')

    def test_nonstring_rule_is_rejected_without_crashing_resolution(self):
        nodes = [{'id': identifier, 'type': 'Gene', 'label': 'A'} for identifier in ('HGNC:10', 'source:10')]
        for rule in ([], {}, None, 1):
            with self.subTest(rule=rule):
                result = resolve_entities(nodes, [{'subject': 'HGNC:10', 'object': 'source:10',
                    'rule': rule, 'provenance': {'row': 1}}])
                self.assertEqual(len(result['nodes']), 2)
                self.assertEqual(result['decisions'][0]['status'], 'rejected_untrusted_rule')

    def test_output_is_deterministic_under_node_and_link_reordering(self):
        nodes = [
            {'id': 'source:gene:z', 'type': 'Gene', 'label': 'WDR45', 'aliases': ['old name'], 'properties': {}},
            {'id': 'HGNC:28912', 'type': 'Gene', 'label': 'WDR45', 'aliases': [], 'properties': {}},
            {'id': 'UniProt:Q9Y2I7', 'type': 'Gene', 'label': 'WIPI4', 'aliases': [], 'properties': {}},
        ]
        links = [
            {'subject': 'source:gene:z', 'object': 'HGNC:28912', 'rule': 'registry_same_as', 'provenance': {'id': 'a'}},
            {'subject': 'UniProt:Q9Y2I7', 'object': 'HGNC:28912', 'rule': 'registry_same_as', 'provenance': {'id': 'b'}},
        ]
        expected = resolve_entities(nodes, links)
        shuffled_nodes = list(nodes)
        shuffled_links = list(links)
        random.Random(4).shuffle(shuffled_nodes)
        random.Random(9).shuffle(shuffled_links)
        self.assertEqual(resolve_entities(shuffled_nodes, shuffled_links), expected)

    def test_incompatible_types_never_merge_even_with_trusted_rule(self):
        nodes = [
            {'id': 'HGNC:1', 'type': 'Gene', 'label': 'Gene', 'aliases': [], 'properties': {}},
            {'id': 'asset:1', 'type': 'Asset', 'label': 'Gene', 'aliases': [], 'properties': {}},
        ]
        result = resolve_entities(nodes, [
            {'subject': nodes[0]['id'], 'object': nodes[1]['id'], 'rule': 'curated_identifier', 'provenance': {'source_id': 'source:trusted'}}
        ])
        self.assertEqual(len(result['nodes']), 2)
        self.assertEqual(result['decisions'][0]['status'], 'rejected_type_mismatch')


if __name__ == '__main__':
    unittest.main()
