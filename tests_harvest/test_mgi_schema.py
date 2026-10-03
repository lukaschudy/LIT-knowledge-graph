import tempfile, unittest
from pathlib import Path
from harvest.mgi_schema import rows

class MGISchemaTests(unittest.TestCase):
    def read(self,name,text):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input';path.write_text(text)
            return list(rows(path,name))
    def test_negation_is_not_lost(self):
        row=self.read('MGI_Geno_NotDiseaseDO','a\tb\tc\td\tMP:1\t123\tMGI:1\tDOID:1\tOMIM:1\tMGI:2\n')[0]
        self.assertEqual(row['qualifier'],'NOT')
        self.assertEqual(row['disease_ids'],'DOID:1')
    def test_disease_only_row_is_not_a_model(self):
        row=self.read('MGI_DiseaseMouseModel','Disease\tDOID:1'+12*'\t'+'\n')[0]
        self.assertFalse(row['has_mouse_model_record'])
        self.assertEqual(len(row['native_columns']),14)
    def test_unexplained_nonempty_columns_fail(self):
        with self.assertRaises(ValueError):self.read('MGI_Strain','MGI:1\tS\tinbred\tunexpected\n')
