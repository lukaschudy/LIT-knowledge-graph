"""Scientific boundary tests for source-specific harvested graph adapters."""
import unittest

from atlas.harvest_graph.adapters import adapt


def edge_set(source, dataset, row):
    nodes, edges = adapt(source, dataset, row)
    return {node["id"]: node for node in nodes}, set(edges)


class HarvestAdapterTests(unittest.TestCase):
    def test_clingen_classification_is_an_assertion_not_gene_disease_truth(self):
        nodes, edges = edge_set("clingen", "gene_disease_validity", {
            "GENE SYMBOL": "AARS1", "GENE ID (HGNC)": "HGNC:20",
            "DISEASE LABEL": "CMT", "DISEASE ID (MONDO)": "MONDO:0013212",
            "CLASSIFICATION": "Refuted", "ONLINE REPORT": "https://example.org/CGGV:abc",
            "MOI": "AD",
        })
        self.assertIn(("HGNC:20", "HAS_CLINGEN_ASSERTION", "ClinGenAssertion:CGGV-abc"), edges)
        self.assertIn(("ClinGenAssertion:CGGV-abc", "ASSERTS_RELATION_TO_DISEASE", "MONDO:0013212"), edges)
        self.assertIn(("ClinGenAssertion:CGGV-abc", "HAS_CLASSIFICATION", "ClinGenClassification:Refuted"), edges)
        self.assertNotIn(("HGNC:20", "ASSOCIATED_WITH_DISEASE", "MONDO:0013212"), edges)
        self.assertEqual(nodes["ClinGenAssertion:CGGV-abc"]["type"], "Assertion")

    def test_clingen_dosage_assertions_keep_haplo_and_triplo_separate(self):
        _, edges = edge_set("clingen", "gene_dosage", {
            "GENE SYMBOL": "A4GALT", "HGNC ID": "HGNC:18149",
            "HAPLOINSUFFICIENCY": "Sufficient Evidence for Haploinsufficiency",
            "TRIPLOSENSITIVITY": "No Evidence for Triplosensitivity",
        })
        assertions = {obj for _, predicate, obj in edges
                      if predicate in {"HAS_HAPLOINSUFFICIENCY_ASSERTION", "HAS_TRIPLOSENSITIVITY_ASSERTION"}}
        self.assertEqual(len(assertions), 2)
        self.assertNotEqual(*sorted(assertions))

    def test_clingen_assertions_without_report_have_deterministic_content_identity(self):
        record = {"GENE ID (HGNC)": "HGNC:20", "DISEASE ID (MONDO)": "MONDO:123",
                  "MOI": "AD", "CLASSIFICATION": "Disputed"}
        nodes, edges = edge_set("clingen", "gene_disease_validity", record)
        assertions = [node for node in nodes if node.startswith("ClinGenAssertion:")]
        self.assertEqual(len(assertions), 1)
        self.assertTrue(any(obj == assertions[0] for _, predicate, obj in edges if predicate == "HAS_CLINGEN_ASSERTION"))
        nodes_again, _ = edge_set("clingen", "gene_disease_validity", record)
        self.assertIn(assertions[0], nodes_again)

    def test_reactome_retains_nonhuman_species_and_normalizes_ids(self):
        nodes, edges = edge_set("reactome", "UniProt2Reactome_All_Levels", {
            "uniprot_accession": "P12345", "reactome_pathway_id": "R-DME-1500931",
            "pathway_name": "Cell communication", "species": "Drosophila melanogaster",
        })
        self.assertIn("UniProt:P12345", nodes)
        self.assertIn("Reactome:R-DME-1500931", nodes)
        self.assertIn(("UniProt:P12345", "PARTICIPATES_IN_PATHWAY", "Reactome:R-DME-1500931"), edges)
        self.assertIn(("Reactome:R-DME-1500931", "PATHWAY_IN_SPECIES", "NCBITaxon:7227"), edges)

    def test_mouse_homology_rows_do_not_require_same_row_human_counterpart(self):
        nodes, edges = edge_set("mgi", "hom_allorganism", {
            "homology_class": "52125027", "organism": "mouse, laboratory", "taxon_id": "10090",
            "symbol": "Aldh1l1", "entrez_id": "107747", "mouse_mgi_id": "MGI:1340024",
            "hgnc_id": "", "omim_id": "",
        })
        self.assertIn(("MGI:1340024", "MEMBER_OF_HOMOLOGY_GROUP", "MGIHomology:52125027"), edges)
        self.assertIn(("MGI:1340024", "IN_SPECIES", "NCBITaxon:10090"), edges)
        self.assertNotIn("HGNC:None", nodes)

    def test_obo_list_fields_and_negative_go_qualifier_are_preserved(self):
        nodes, edges = edge_set("go", "ontology", {
            "id": ["GO:0000001"], "name": ["mitochondrion inheritance"],
            "is_a": ["GO:0048308 ! organelle inheritance"],
        })
        self.assertIn("GO:0000001", nodes)
        self.assertIn(("GO:0000001", "IS_A", "GO:0048308"), edges)
        _, edges = edge_set("go", "human_annotations", {
            "db": "UniProtKB", "db_object_id": "Q12879", "db_object_symbol": "GRIN2A",
            "qualifier": "NOT|involved_in", "go_id": "GO:0005515", "aspect": "P",
        })
        self.assertIn(("UniProt:Q12879", "NOT_ANNOTATED_WITH_GO", "GO:0005515"), edges)
        self.assertNotIn(("UniProt:Q12879", "PARTICIPATES_IN_BIOLOGICAL_PROCESS", "GO:0005515"), edges)

    def test_orphadata_uses_explicit_ensembl_cross_reference(self):
        row = {"tag": "Disorder", "attributes": {"id": "1"}, "children": [
            {"tag": "OrphaCode", "text": "166024", "children": []},
            {"tag": "Name", "text": "Example disease", "children": []},
            {"tag": "DisorderGeneAssociation", "children": [
                {"tag": "Gene", "attributes": {"id": "20160"}, "children": [
                    {"tag": "Symbol", "text": "KIF7", "children": []},
                    {"tag": "ExternalReference", "children": [
                        {"tag": "Source", "text": "Ensembl", "children": []},
                        {"tag": "Reference", "text": "ENSG00000166813", "children": []},
                    ]},
                ]},
            ]},
        ]}
        _, edges = edge_set("orphadata", "genes", row)
        self.assertIn(("Orphanet:166024", "ASSOCIATED_WITH_GENE", "ENSG00000166813"), edges)

    def test_non_med_epmc_identifiers_are_one_valid_curie_and_no_author_name_merge(self):
        nodes, edges = edge_set("europe_pmc_diseases", "articles", {
            "id": "9915602234507426", "source": "AGR", "title": "Example",
            "authorList": {"author": [{"fullName": "A. Example", "authorId": {
                "type": "ORCID", "value": "0000-0002-1825-0097"}}]},
        })
        self.assertIn("EPMC:AGR-9915602234507426", nodes)
        self.assertIn("ORCID:0000-0002-1825-0097", nodes)
        self.assertIn(("ORCID:0000-0002-1825-0097", "AUTHORED", "EPMC:AGR-9915602234507426"), edges)
        self.assertEqual(nodes["ORCID:0000-0002-1825-0097"]["label"], "A. Example")

    def test_clinvar_many_explicit_hgnc_ids_are_all_linked_without_label_guess(self):
        nodes, edges = edge_set("clinvar", "variant_summary", {
            "VariationID": 42, "HGNC_ID": "HGNC:1|HGNC:2", "GeneSymbol": "GENEA",
            "PhenotypeIDS": "MONDO:MONDO:0001234",
        })
        self.assertIn(("ClinVar:42", "IN_GENE", "HGNC:1"), edges)
        self.assertIn(("ClinVar:42", "IN_GENE", "HGNC:2"), edges)
        self.assertEqual(nodes["HGNC:2"]["label"], "HGNC:2")
        self.assertIn(("ClinVar:42", "HAS_CLINVAR_CONDITION", "MONDO:0001234"), edges)

    def test_hpo_wrapper_alias_preserves_negative_association(self):
        _, edges = edge_set("grin_reference", "hpo_disease_phenotypes", {
            "_dataset": "hpo_disease_phenotypes",
            "native": {"database_id": "OMIM:123", "disease_name": "D",
                       "qualifier": "NOT", "hpo_id": "HP:0000001"},
        })
        self.assertIn(("OMIM:123", "NOT_HAS_PHENOTYPE", "HP:0000001"), edges)

    def test_full_text_queues_keep_explicit_publication_ids(self):
        nodes, edges = edge_set("pmc_grin_oa", "no_pmcid_queue", {
            "pmid": "7524561", "title": "A paper with no PMC id",
        })
        self.assertIn("PMID:7524561", nodes)

    def test_unknown_rows_stay_unmapped_and_all_labels_are_bounded(self):
        self.assertEqual(adapt("unknown", "unknown", {"id": "x"}), ([], []))
        nodes, _ = edge_set("hgnc", "hgnc_complete_set", {
            "hgnc_id": "HGNC:123", "symbol": "X" * 1000,
        })
        self.assertLessEqual(len(nodes["HGNC:123"]["label"]), 300)


if __name__ == "__main__":
    unittest.main()
