import unittest
from harvest.grin_review_queue import extract_entries, extract_paragraph, extract_table_candidates

class GrinReviewQueueTests(unittest.TestCase):
    def test_extracts_only_named_grin2a_and_grin2b_variants_by_category(self):
        p = ("Likely GoF published variants include GluN2A-E551K and GluN2B-S555N. "
             "Possible GoF published variants include GluN2B-S541G. "
             "Likely LoF published variants include GluN2A-G483R. "
             "Possible LoF variants include GluN2B-C461F. "
             "classified variants with expression too low to measure responses (GluN2B-C436R) as Likely LoF. "
             "Six published variants had No Effect or were Indeterminant (GluN2B-R540H).")
        entries = extract_entries(p)
        self.assertEqual(len(entries), 7)
        self.assertEqual(entries[0]['author_category'], 'Likely GoF')
        self.assertEqual(entries[2]['protein_change'], 'p.Ser541Gly')
        self.assertEqual(entries[-1]['author_category'], 'No Effect or Indeterminant (grouped by source)')

    def test_table1_candidates_keep_text_class_and_mark_missing_class(self):
        labels = ["I150V", "E657D"] + [f"A{i}V" for i in range(1, 13)]
        rows = ''.join(f'<tr><td>{x}</td><td>data</td></tr>' for x in ["GRIN2B variant"] + labels)
        table6 = ('<tr><td>I150V</td><td>Indeterminant</td></tr>'
                  '<tr><td>E657D</td><td>Indeterminant</td></tr>')
        html = f'<section id="TB1"><table>{rows}</table></section><section id="TB6"><table>{table6}</table></section>'
        candidates = extract_table_candidates(html, {"variants": []})
        self.assertEqual(len(candidates), 14)
        calls = {x['source_protein_notation']: x['author_category'] for x in candidates}
        self.assertEqual(calls['GluN2B-I150V'], 'Indeterminant')
        self.assertEqual(calls['GluN2B-E657D'], 'Indeterminant')
        self.assertTrue(all(x['cohort_admission'] == 'not_automatically_admitted' for x in candidates))
        self.assertEqual(sum(x['classification_status'] == 'available_as_text_in_Table_6' for x in candidates), 2)
        self.assertEqual(sum(x['classification_status'] != 'available_as_text_in_Table_6' for x in candidates), 12)

    def test_finds_single_paragraph_with_all_sections(self):
        html = '<p>Likely GoF published variants include GluN2A-E551K. Possible GoF published variants include GluN2B-S541G. Likely LoF published variants include GluN2A-G483R. Possible LoF variants include GluN2B-C461F. classified variants with expression too low to measure responses (GluN2B-C436R) as Likely LoF. Six published variants had No Effect or were Indeterminant (GluN2B-R540H).</p>'
        self.assertIn('Six published variants', extract_paragraph(html))

if __name__ == '__main__':
    unittest.main()
