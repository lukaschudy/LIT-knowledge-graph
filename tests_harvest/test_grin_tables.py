import unittest
from harvest.grin_tables import Tables

class TablePreservationTests(unittest.TestCase):
    def test_image_only_value_is_flagged_and_spans_preserved(self):
        p=Tables();p.feed('<table id="T1"><tr><td rowspan="2">G533D</td><td><img src="value.gif" alt="Inline graphic"></td><td colspan="3">2.0</td></tr></table>')
        row=p.rows[0]
        self.assertEqual(row['cells'],['G533D','','2.0'])
        self.assertTrue(row['contains_untranscribed_images'])
        self.assertEqual(row['cell_metadata'][1]['images'][0]['src'],'value.gif')
        self.assertEqual(row['cell_metadata'][0]['rowspan'],'2')
        self.assertEqual(row['cell_metadata'][2]['colspan'],'3')
