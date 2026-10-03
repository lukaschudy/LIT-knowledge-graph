import tempfile, unittest
from pathlib import Path
from harvest.community import rare_rows, DirectoryParser

class CommunityTests(unittest.TestCase):
    def test_export_preamble_footer_not_records(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'d.csv'
            p.write_text('RARe-SOURCE copyright,\n\nRare Disease Name,OMIM\nExample,1\nThis file was downloaded from RARe-SOURCE,\n')
            self.assertEqual(list(rare_rows(p)),[{'Rare Disease Name':'Example','OMIM':'1'}])
    def test_directory_excludes_navigation_and_footer(self):
        p=DirectoryParser();p.feed('<a href="https://nav.org">Nav</a><h5 id="A-list">A</h5><ul><li><a href="https://a.org">A &amp; B</a></li></ul><footer><ul><a href="https://footer.org">Footer</a></ul></footer>')
        self.assertEqual(p.records,[{'name':'A & B','url':'https://a.org','directory_section':'A'}])

if __name__=='__main__':unittest.main()
