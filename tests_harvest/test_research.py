import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import json

from harvest import research


class ResearchParsingTests(unittest.TestCase):
    def test_pmc_jats_validation_requires_exact_id_and_body(self):
        import xml.etree.ElementTree as ET
        wrong=ET.fromstring('<article><front><article-meta><article-id pub-id-type="pmcid">PMC2</article-id></article-meta></front><body>Text</body></article>')
        metadata_only=ET.fromstring('<article><front><article-meta><article-id pub-id-type="pmcid">PMC1</article-id></article-meta></front></article>')
        full=ET.fromstring('<article><front><article-meta><article-id pub-id-type="pmcid">1</article-id></article-meta></front><body>Text</body></article>')
        self.assertEqual(research._pmc_jats_error(wrong,"PMC1"),("fulltext_pmcid_mismatch","PMC2"))
        self.assertEqual(research._pmc_jats_error(metadata_only,"PMC1"),("fulltext_body_missing","PMC1"))
        self.assertEqual(research._pmc_jats_error(full,"PMC1"),(None,"PMC1"))

    def test_pubmed_parser_preserves_sections_identifiers_and_mesh(self):
        import xml.etree.ElementTree as ET
        article = ET.fromstring('''<PubmedArticle><MedlineCitation><PMID>123</PMID>
          <Article><ArticleTitle>Example disease</ArticleTitle><Abstract><AbstractText Label="RESULTS">A &amp; B</AbstractText></Abstract>
          <Journal><Title>Journal</Title><ISSN>1234-5678</ISSN></Journal></Article>
          <MeshHeadingList><MeshHeading><DescriptorName UI="D1">Disease</DescriptorName></MeshHeading></MeshHeadingList>
          </MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="doi">10/x</ArticleId></ArticleIdList></PubmedData></PubmedArticle>''')
        parsed = research._pubmed_record(article)
        self.assertEqual(parsed["pmid"], "123")
        self.assertEqual(parsed["abstract_sections"][0]["text"], "A & B")
        self.assertEqual(parsed["mesh_headings"][0]["descriptor_ui"], "D1")

    def test_pubmed_book_article_keeps_pmid_and_raw_record(self):
        import xml.etree.ElementTree as ET
        node=ET.fromstring('<PubmedBookArticle><BookDocument><PMID>987</PMID><Book><BookTitle>Rare disorders</BookTitle></Book></BookDocument></PubmedBookArticle>')
        parsed=research._pubmed_record(node)
        self.assertEqual(parsed["pmid"],"987")
        self.assertIn("PubmedBookArticle",parsed["raw_xml"])

    def test_pubmed_article_ids_exclude_pmcids_from_references(self):
        import xml.etree.ElementTree as ET
        article = ET.fromstring('''<PubmedArticle><MedlineCitation><PMID>123</PMID><Article>
          <ArticleTitle>Current article</ArticleTitle></Article><ReferenceList><Reference><ArticleIdList>
          <ArticleId IdType="pmc">PMC999</ArticleId></ArticleIdList></Reference></ReferenceList>
          </MedlineCitation><PubmedData><ArticleIdList><ArticleId IdType="pmc">PMC123</ArticleId>
          <ArticleId IdType="doi">10/current</ArticleId></ArticleIdList></PubmedData></PubmedArticle>''')
        parsed = research._pubmed_record(article)
        self.assertEqual(parsed["article_ids"], [{"type": "pmc", "value": "PMC123"},
                                                  {"type": "doi", "value": "10/current"}])

    def test_pubmed_id_set_audit_reports_missing_and_unexpected(self):
        audit=research.pubmed_id_coverage({"1","2","3"},{"1","2","4"})
        self.assertEqual(audit["missing_ids"],["3"])
        self.assertEqual(audit["unexpected_ids"],["4"])

    def test_broad_pubmed_query_is_explicit(self):
        self.assertEqual(research.PUBMED_QUERY,
                         '("Rare Diseases"[MeSH Terms] OR rare disease*[Title/Abstract] OR orphan disease*[Title/Abstract])')

    def test_ctg_batches_keep_preferred_name_lists(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/"diseases.jsonl.gz"
            import gzip
            with gzip.open(path,"wt",encoding="utf-8") as out:
                for name in ("Disease A","Disease B","Disease C"):
                    out.write(json.dumps({"Rare Disease Name":name})+"\n")
            batches=list(research._disease_batches(path,max_chars=14))
        self.assertEqual(batches,[["Disease A"],["Disease B"],["Disease C"]])

    def test_ctg_condition_strips_grouping_punctuation_safely(self):
        self.assertEqual(research._ctg_condition(["Disease (type 1)", "A \"quoted\" disorder"]),
                         '"Disease type 1" OR "A quoted disorder"')


class PagedSourceTests(unittest.TestCase):
    def test_clinical_trials_follows_every_next_page_and_deduplicates(self):
        pages = [
            {"studies": [{"protocolSection": {"identificationModule": {"nctId": "NCT1"}}}], "nextPageToken": "next"},
            {"studies": [{"protocolSection": {"identificationModule": {"nctId": "NCT1"}}},
                         {"protocolSection": {"identificationModule": {"nctId": "NCT2"}}}]},
        ]
        paths=[]
        with tempfile.TemporaryDirectory() as td:
            with patch.object(research.core, "PROCESSED", Path(td)/"processed"):
                def fake_download(source, url, filename, **kwargs):
                    payload=pages.pop(0) if pages else {"studies": []}
                    path=Path(td)/filename; path.write_text(json.dumps(payload)); paths.append(url); return path
                with patch.object(research.core, "download", side_effect=fake_download), \
                     patch.object(research.core, "emit_records", side_effect=lambda source,name,records,**kw:list(records)), \
                     patch.object(research.core, "update_manifest"):
                    rows=research.harvest_clinicaltrials()
        self.assertEqual({r["protocolSection"]["identificationModule"]["nctId"] for r in rows}, {"NCT1", "NCT2"})
        self.assertEqual(len(paths), len(research.CTG_TERMS)+1)
        self.assertIn("pageToken=next", paths[1])


if __name__ == "__main__":
    unittest.main()
