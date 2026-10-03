"""Public provider exports and directory metadata, without member-only content."""
import argparse, csv, re
from html.parser import HTMLParser
from pathlib import Path
from harvest.core import download, emit_records, import_export, update_manifest, open_text

def rare_rows(path):
    with open_text(path) as f:
        rows=csv.reader(f)
        for row in rows:
            if row and row[0] in ('Rare Disease Name','Gene Information'):
                header=row;break
        else:raise ValueError('Missing RARe-SOURCE export header')
        for row in rows:
            if not row or row[0].startswith('This file was downloaded from RARe-SOURCE'):continue
            if len(row)!=len(header):raise ValueError('RARe-SOURCE column count mismatch')
            yield dict(zip(header,row))

def rare_export(path,kind,expected):
    p=import_export('raresource',path,kind+'.csv',url='https://raresource.nih.gov/'+kind+'/',
        license_name='Public table export; upstream integrated rights apply; redistribution not established',expected_records=expected)
    rows=list(rare_rows(p))
    if len(rows)!=expected:raise ValueError(f'Expected {expected}, exported {len(rows)}')
    emit_records('raresource',kind,rows,input_paths=[p],description='All rows from the public table export; UI count matched exactly. Native fields retained.')
    update_manifest('raresource',status='complete_for_scope',scope='Public disease and gene tables; curated literature annotations and variants are separate products, not yet included.')

class DirectoryParser(HTMLParser):
    def __init__(self):
        super().__init__();self.active=False;self.list_depth=0;self.anchor=None;self.records=[];self.letter=None
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='h5' and re.fullmatch('[A-Z]-list',a.get('id','')):
            self.active=True;self.letter=a['id'][0]
        if self.active and tag=='ul':self.list_depth+=1
        if self.active and self.list_depth and tag=='a' and a.get('href','').startswith(('https://','http://')):
            self.anchor={'name':'','url':a['href'],'directory_section':self.letter}
        if tag=='footer':self.active=False
    def handle_data(self,data):
        if self.anchor is not None:self.anchor['name']+=data
    def handle_endtag(self,tag):
        if tag=='a' and self.anchor is not None:
            self.anchor['name']=' '.join(self.anchor['name'].split());self.records.append(self.anchor);self.anchor=None
        if tag=='ul' and self.list_depth:
            self.list_depth-=1
            if self.list_depth==0:self.active=False

def gauk():
    url='https://geneticalliance.org.uk/membership/a-z-members-directory/'
    p=download('genetic_alliance_uk',url,'members.html',license_name='Genetic Alliance UK website terms; attribution, noncommercial unmodified reuse; verify permission for redistribution')
    parser=DirectoryParser();parser.feed(p.read_text())
    if not parser.records:raise ValueError('No directory entries')
    emit_records('genetic_alliance_uk','member_organizations',parser.records,input_paths=[p],description='All external organization links within the A–Z member lists. Attribution: Genetic Alliance UK.')
    update_manifest('genetic_alliance_uk',status='complete_for_scope',scope='Entire public A–Z directory snapshot; membership is not endorsement or disease-association evidence.')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['gauk','raresource']);p.add_argument('--path');p.add_argument('--kind',choices=['diseases','genes']);p.add_argument('--expected',type=int);a=p.parse_args()
    if a.command=='gauk':gauk()
    else:rare_export(a.path,a.kind,a.expected)
