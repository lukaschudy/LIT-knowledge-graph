"""Acquisition of literature and study records relevant to rare diseases.

These functions preserve source records and search provenance. They do not
assert that a record proves a biological or clinical relationship.
"""
from __future__ import annotations

import argparse
import calendar
from collections import Counter
import json
import hashlib
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode, urlsplit, parse_qs

import requests

from harvest import core

PUBMED_QUERY = '("Rare Diseases"[MeSH Terms] OR rare disease*[Title/Abstract] OR orphan disease*[Title/Abstract])'
CTG_TERMS = ["rare disease", "orphan disease", "neurodevelopmental disorder", "inherited disorder"]
REPORTER_QUERY = "rare disease OR orphan disease"
GRIN_QUERY = '(GRIN2A[Title/Abstract] OR GRIN2B[Title/Abstract] OR GluN2A[Title/Abstract] OR GluN2B[Title/Abstract] OR NR2A[Title/Abstract] OR NR2B[Title/Abstract])'
GRIN_FULLTEXT_PMIDS = {"27839871", "38538865", "38380699"}
GRIN_FULLTEXT_PMCIDS = {"PMC7554152"}
GRIN_FULLTEXT_RE = re.compile(r"mutation|variant|encephalopathy|neurodevelopment|loss[ -]?of[ -]?function", re.I)
PUBMED_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CTG_BASE = "https://clinicaltrials.gov/api/v2/studies"
REPORTER_URL = "https://api.reporter.nih.gov/v2/projects/search"
PREPRINT_BASE = "https://api.biorxiv.org/details"


def _get(source: str, url: str, filename: str, license_name: str, version: str = "current") -> Path:
    return core.download(source, url, filename, license_name=license_name, version=version)


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _xml_records(path: Path, tag: str):
    root = ET.parse(path).getroot()
    return list(root.findall(f".//{tag}"))


def _text(el):
    return "".join(el.itertext()).strip() if el is not None else None


def _pubmed_record(article):
    if article.tag == "PubmedBookArticle":
        pmid = _text(article.find("./BookDocument/PMID"))
    else:
        pmid = _text(article.find("./MedlineCitation/PMID"))
    citation = article.find("MedlineCitation")
    art = citation.find("Article") if citation is not None else None
    if art is None:
        return {"pmid": pmid, "raw_xml": ET.tostring(article, encoding="unicode")}
    authors = []
    for author in art.findall("./AuthorList/Author"):
        authors.append({"last_name": _text(author.find("LastName")), "fore_name": _text(author.find("ForeName")),
                        "initials": _text(author.find("Initials")), "collective_name": _text(author.find("CollectiveName")),
                        "identifiers": [{"source": x.get("Source"), "value": _text(x)} for x in author.findall("./Identifier")],
                        "affiliations": [_text(x) for x in author.findall("./AffiliationInfo/Affiliation")]})
    abstract = []
    for section in art.findall("./Abstract/AbstractText"):
        abstract.append({"label": section.get("Label"), "category": section.get("NlmCategory"), "text": _text(section)})
    mesh = []
    for heading in citation.findall("./MeshHeadingList/MeshHeading") if citation is not None else []:
        mesh.append({"descriptor": _text(heading.find("DescriptorName")),
                     "descriptor_ui": heading.find("DescriptorName").get("UI") if heading.find("DescriptorName") is not None else None,
                     "qualifiers": [{"name": _text(q), "ui": q.get("UI")} for q in heading.findall("QualifierName")]})
    ids = []
    # Article-wide IDs live in PubmedData/ArticleIdList. A recursive search also
    # captures PMCIDs of cited papers under ReferenceList and falsely links them
    # to this PMID.
    for node in article.findall("./PubmedData/ArticleIdList/ArticleId"):
        ids.append({"type": node.get("IdType"), "value": _text(node)})
    journal = art.find("Journal")
    return {"pmid": pmid, "title": _text(art.find("ArticleTitle")), "abstract_sections": abstract,
            "authors": authors, "journal": _text(journal.find("Title")) if journal is not None else None,
            "journal_issn": _text(journal.find("ISSN")) if journal is not None else None,
            "publication_types": [_text(x) for x in art.findall("./PublicationTypeList/PublicationType")],
            "mesh_headings": mesh, "keywords": [_text(x) for x in citation.findall("./KeywordList/Keyword")] if citation is not None else [],
            "article_ids": ids, "publication_date": _text(art.find("./Journal/JournalIssue/PubDate")),
            "language": [_text(x) for x in art.findall("./Language")], "raw_xml": ET.tostring(article, encoding="unicode")}


def pubmed_id_coverage(expected_ids, retrieved_ids):
    """Return the exact-set audit used before a PubMed dataset is marked complete."""
    expected=set(expected_ids); retrieved=set(retrieved_ids)
    return {"expected_unique_ids":len(expected),"retrieved_unique_ids":len(retrieved),
            "missing_ids":sorted(expected-retrieved),"unexpected_ids":sorted(retrieved-expected)}


def _pmc_jats_error(article, expected_pmcid):
    """Reject metadata-only responses, mismatched article IDs, and empty full-text bodies."""
    found=article.find(".//article-id[@pub-id-type='pmc']")
    if found is None: found=article.find(".//article-id[@pub-id-type='pmcid']")
    returned=(_text(found) or "").upper()
    if returned and not returned.startswith("PMC"): returned="PMC"+returned
    if returned!=expected_pmcid: return "fulltext_pmcid_mismatch",returned
    body=article.find(".//body")
    if body is None or not _text(body): return "fulltext_body_missing",returned
    return None,returned


class _PmcArticleHtmlParser(HTMLParser):
    """Collect only rendered text under PMC's main article region and identity metadata."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.main_depth=0; self.article_depth=0; self.p_depth=0
        self.main_text=[]; self.article_text=[]; self.paragraphs=[]; self.current_paragraph=[]
        self.canonical=[]; self.pmid=None; self.title=None
    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        if tag=="meta":
            name=(attrs.get("name") or "").lower()
            if name=="citation_pmid": self.pmid=attrs.get("content")
            if name=="citation_title": self.title=attrs.get("content")
        if tag=="link" and "canonical" in (attrs.get("rel") or "").lower(): self.canonical.append(attrs.get("href",""))
        if tag=="main" and attrs.get("id")=="main-content": self.main_depth+=1
        elif self.main_depth:
            if tag=="main": self.main_depth+=1
        if self.main_depth and tag=="article": self.article_depth+=1
        if self.main_depth and tag=="p":
            self.p_depth+=1
            if self.p_depth==1: self.current_paragraph=[]
    def handle_endtag(self, tag):
        if self.main_depth and tag=="p" and self.p_depth:
            self.p_depth-=1
            if self.p_depth==0:
                text=" ".join("".join(self.current_paragraph).split())
                if text: self.paragraphs.append(text)
                self.current_paragraph=[]
        if self.main_depth and tag=="article" and self.article_depth: self.article_depth-=1
        if tag=="main" and self.main_depth: self.main_depth-=1
    def handle_data(self, data):
        if not self.main_depth: return
        if self.p_depth: self.current_paragraph.append(data)
        if self.article_depth: self.article_text.append(data)
        self.main_text.append(data)


def _pmc_html_validation(html, expected_pmcid):
    parser=_PmcArticleHtmlParser()
    try: parser.feed(html); parser.close()
    except Exception as exc: return {"ok":False,"status":"invalid_html","error":str(exc)[:300]}
    canonical=" ".join(parser.canonical)
    canonical_match=bool(re.search(r"/articles/"+re.escape(expected_pmcid)+r"/?(?:$|[?#])",canonical))
    text=" ".join(" ".join(parser.main_text).split())
    article_text=" ".join(" ".join(parser.article_text).split())
    challenge_patterns=("captcha","verify you are human","checking your browser","access denied",
                        "robot check","sign in to continue","log in to continue","temporarily blocked")
    lower=text.lower()
    challenge=next((phrase for phrase in challenge_patterns if phrase in lower),None)
    if not canonical_match:
        return {"ok":False,"status":"html_identity_mismatch","canonical":parser.canonical,"pmid":parser.pmid}
    if challenge:
        return {"ok":False,"status":"html_challenge_or_login","challenge_marker":challenge,"canonical":parser.canonical}
    if parser.pmid is None or len(article_text)<1000 or len(text)<1200 or len(parser.paragraphs)<3:
        return {"ok":False,"status":"html_body_not_substantial","canonical":parser.canonical,"pmid":parser.pmid,
                "main_text_chars":len(text),"article_text_chars":len(article_text),"paragraphs":len(parser.paragraphs)}
    return {"ok":True,"status":"validated_html_full_text","canonical_url":parser.canonical[0],"pmid":parser.pmid,
            "title":parser.title,"body_text":article_text,"main_text_chars":len(text),"article_text_chars":len(article_text),
            "paragraphs":len(parser.paragraphs)}


def _esearch(term, retstart, retmax, email, tool, source="pubmed"):
    params = {"db": "pubmed", "term": term, "retmode": "json", "retmax": retmax, "retstart": retstart,
              "tool": tool}
    if email: params["email"] = email
    url=f"{PUBMED_BASE}/esearch.fcgi?"+urlencode(params)
    name="search-"+hashlib.sha256(url.encode()).hexdigest()+".json"
    result=_json(_get(source,url,name,"PubMed citation metadata","queried"))["esearchresult"]
    time.sleep(.36)
    return result


def harvest_pubmed(email: str | None = None, tool: str = "LIT-knowledge-graph", start_year: int = 1900, end_year: int | None = None,
                   query: str = PUBMED_QUERY, source: str = "pubmed", dataset_name: str = "rare_disease_citations"):
    """Harvest every PMID matching the query, partitioning large year buckets."""
    end_year = end_year or date.today().year
    ids, partitions = set(), []
    def collect(term, label):
        result = _esearch(term, 0, 0, email, tool, source)
        count = int(result["count"])
        if count > 9999:
            # Split by calendar year; for an exceptional >10k year, split into months.
            if label.isdigit() and len(label)==4:
                year = int(label)
                for month in range(1, 13):
                    last = calendar.monthrange(year, month)[1]
                    dated = f'{term} AND ("{year}/{month:02d}/01"[Date - Publication] : "{year}/{month:02d}/{last:02d}"[Date - Publication])'
                    collect(dated, f"{year}-{month:02d}")
                return
            if len(label)==7 and label[4]=="-":
                year,month=map(int,label.split("-")); last=calendar.monthrange(year,month)[1]
                for day in range(1,last+1):
                    dated=f'{term} AND ("{year}/{month:02d}/{day:02d}"[Date - Publication])'
                    collect(dated,f"{year}-{month:02d}-{day:02d}")
                return
            if ":" not in label:
                raise RuntimeError(f"Unpartitionable PubMed search with {count} results: {label}")
            lo, hi = map(int, label.split(":", 1))
            if lo < hi:
                mid = (lo + hi) // 2
                collect(f'{term} AND ("{lo}"[Date - Publication] : "{mid}"[Date - Publication])', f"{lo}:{mid}")
                collect(f'{term} AND ("{mid+1}"[Date - Publication] : "{hi}"[Date - Publication])', f"{mid+1}:{hi}")
                return
            raise RuntimeError(f"Unpartitionable PubMed search with {count} results: {label}")
        allids=[]
        for offset in range(0, count, 10000):
            page = _esearch(term, offset, min(10000, count-offset), email, tool, source)
            allids.extend(page.get("idlist", []))
        ids.update(allids); partitions.append({"partition": label, "count": count, "ids_returned": len(allids)})
    # Year slicing prevents ESearch's 10,000 ID response ceiling from hiding matches.
    for year in range(start_year, end_year + 1):
        collect(f'{query} AND ("{year}"[Date - Publication])', str(year))
    if not ids:
        raise RuntimeError("PubMed query returned no IDs; refusing to mark harvest complete")
    records=[]; ordered=sorted(ids, key=lambda x: int(x))
    for pos in range(0, len(ordered), 200):
        chunk=ordered[pos:pos+200]
        key=f"efetch-{pos:09d}.xml"
        params={"db":"pubmed","id":",".join(chunk),"retmode":"xml","tool":tool}
        if email: params["email"]=email
        url=f"{PUBMED_BASE}/efetch.fcgi?"+urlencode(params)
        path=_get(source,url,key,"PubMed citation metadata; abstract rights vary by publisher", "queried-"+str(end_year))
        xml_root=ET.parse(path).getroot()
        records.extend(_pubmed_record(x) for x in list(xml_root.findall(".//PubmedArticle"))+list(xml_root.findall(".//PubmedBookArticle")))
        if pos + 200 < len(ordered): time.sleep(.51)
    seen={};
    for r in records:
        if r.get("pmid"): seen[r["pmid"]]=r
    out=core.emit_records(source,dataset_name,seen.values(),input_paths=[core.RAW/source],
        description=f'PubMed query: {query}; publication years {start_year}-{end_year}.')
    id_audit=pubmed_id_coverage(ids,seen)
    partition_mismatches=[x for x in partitions if x["count"]!=x["ids_returned"]]
    complete=not id_audit["missing_ids"] and not id_audit["unexpected_ids"] and not partition_mismatches
    core.update_manifest(source,status="complete" if complete else "partial_efetch_coverage",query=query,coverage={"start_year":start_year,"end_year":end_year,
        "matching_unique_pmids":len(seen),"search_partition_occurrences":sum(x["count"] for x in partitions),"partitions":partitions,
        "partition_count_mismatches":partition_mismatches,"missing_fetched_pmids":id_audit["missing_ids"],"unexpected_fetched_pmids":id_audit["unexpected_ids"],"exact_id_set_match":complete,
        "limitation":"Search retrieves title/abstract/index matches; papers discussing relevant concepts without these terms can be missed."})
    return out


def normalize_pubmed_cache(source="pubmed", dataset_name="rare_disease_citations", query=PUBMED_QUERY):
    """Rebuild PubMed JSONL from cached ESearch/EFetch XML and audit ID coverage."""
    m=core.manifest(source); artifacts=m.get("artifacts",{}); expected=set(); partition_map={}
    rawdir=core.RAW/source
    for filename,entry in artifacts.items():
        if not filename.startswith("search-") or "email=" in entry.get("url",""): continue
        payload=_json(rawdir/filename).get("esearchresult",{})
        ids=payload.get("idlist",[]); expected.update(ids)
        params=parse_qs(urlsplit(entry.get("url","")).query)
        term=(params.get("term") or [""])[0]
        retmax=int((params.get("retmax") or [0])[0]); retstart=int((params.get("retstart") or [0])[0])
        if not retmax or (query not in term and not all(x in term for x in ("GRIN2A","GRIN2B"))):
            continue
        row=partition_map.setdefault(term,{"query":term,"reported_count":int(payload.get("count",0)),"ids":set(),"page_offsets":[]})
        row["ids"].update(ids); row["page_offsets"].append(retstart)
    partition_rows=[]
    for row in partition_map.values():
        partition_rows.append({"query":row["query"],"reported_count":row["reported_count"],"ids_returned":len(row["ids"]),"page_offsets":sorted(row["page_offsets"])})
    records={}; returned=set()
    for filename in sorted(x for x in artifacts if x.startswith("efetch-") and x.endswith(".xml")):
        root=ET.parse(rawdir/filename).getroot()
        for node in list(root.findall(".//PubmedArticle"))+list(root.findall(".//PubmedBookArticle")):
            record=_pubmed_record(node); pmid=record.get("pmid")
            if pmid:
                records[pmid]=record; returned.add(pmid)
    id_audit=pubmed_id_coverage(expected,returned)
    partition_mismatches=[x for x in partition_rows if x["reported_count"]!=x["ids_returned"]]
    if not records: raise RuntimeError(f"{source}: no citation records could be normalized from cached EFetch files")
    out=core.emit_records(source,dataset_name,records.values(),input_paths=[rawdir],description=f"PubMed XML normalized from complete cached EFetch files for query: {query}.")
    complete=not id_audit["missing_ids"] and not id_audit["unexpected_ids"] and not partition_mismatches
    core.update_manifest(source,status="complete" if complete else "partial_efetch_coverage",query=query,
        coverage={"query_partition_requests":len(partition_rows),"query_partition_occurrences":sum(x["reported_count"] for x in partition_rows),
                  "unique_searched_pmids":len(expected),"unique_fetched_pmids":len(returned),"normalized_records":len(records),
                  "missing_fetched_pmids":id_audit["missing_ids"],"unexpected_fetched_pmids":id_audit["unexpected_ids"],"exact_id_set_match":not id_audit["missing_ids"] and not id_audit["unexpected_ids"],"partitions":partition_rows,
                  "partition_count_mismatches":partition_mismatches,
                  "limitation":"Broad generic rare/orphan-disease query; disease-name-specific and phenotype-only studies can be missed."})
    return out


def harvest_grin_pubmed(email: str | None = None):
    """Harvest every PubMed title/abstract match for GRIN2A/GRIN2B and aliases."""
    return harvest_pubmed(email=email,query=GRIN_QUERY,source="grin_literature",dataset_name="grin_gene_citations")


def harvest_clinicaltrials(page_size=1000):
    source="clinicaltrials_gov"; unique={}; searches=[]
    for term in CTG_TERMS:
        token=None; count=0; page=0
        while True:
            params={"query.cond":term,"pageSize":page_size,"format":"json","countTotal":"true"}
            if token: params["pageToken"]=token
            url=CTG_BASE+"?"+urlencode(params)
            path=_get(source,url,f"search-{len(searches):02d}-{page:05d}.json","U.S. federal public registry data","API v2")
            payload=_json(path); studies=payload.get("studies",[])
            if not studies: break
            for study in studies:
                ident=study.get("protocolSection",{}).get("identificationModule",{}).get("nctId")
                if ident:
                    previous=unique.get(ident)
                    if previous:
                        membership=previous.setdefault("query_membership",[])
                        entry={"query_set":"generic_terms","terms":[term]}
                        if entry not in membership: membership.append(entry)
                    else:
                        study["query_membership"]=[{"query_set":"generic_terms","terms":[term]}]
                        unique[ident]=study
            count+=len(studies); page+=1; token=payload.get("nextPageToken")
            if not token: break
            time.sleep(.15)
        searches.append({"term":term,"records_seen":count,"pages":page})
    if not unique: raise RuntimeError("ClinicalTrials.gov returned no study records")
    existing_path=core.PROCESSED/source/"rare_disease_studies.jsonl.gz"
    if existing_path.exists():
        for row in core.read_records(existing_path):
            ident=row.get("protocolSection",{}).get("identificationModule",{}).get("nctId")
            if ident and ident not in unique: unique[ident]=row
    out=core.emit_records(source,"rare_disease_studies",unique.values(),input_paths=[core.RAW/source],
        description="Complete paged results for documented broad condition terms; this is not complete coverage of every rare-disease trial.")
    core.update_manifest(source,status="complete",query_terms=CTG_TERMS,coverage={"unique_nct_ids":len(unique),"searches":searches,"limitation":"Generic terms supplement later condition-name searches; broad text search alone cannot enumerate every rare disease trial."})
    return out


def _disease_batches(path, max_chars=400, max_names=4):
    """Yield source names in URL-safe OR batches, preserving every batch list."""
    names=[]; used=0
    for record in core.read_records(path):
        name=(record.get("Rare Disease Name") or "").strip()
        if not name: continue
        cost=len(name)+4
        if names and (used+cost>max_chars or len(names)>=max_names):
            yield names; names=[]; used=0
        names.append(name); used+=cost
    if names: yield names


def _ctg_condition(names):
    clean=[]
    table=str.maketrans({"(":" ",")":" ","[":" ","]":" ","{":" ","}":" ","\"":" ","\\":" "})
    for name in names:
        clean.append('"'+' '.join(name.translate(table).split())+'"')
    return " OR ".join(clean)


def _ctg_name_key(value):
    return re.sub(r"[^a-z0-9]+"," ",value.casefold()).strip()


def audit_ctg_disease_names(path=None, source="clinicaltrials_gov"):
    """Audit cached CTG leaf queries, response counts, page exhaustion and name coverage."""
    path=Path(path or core.PROCESSED/"raresource/diseases.jsonl.gz")
    studies_path=core.PROCESSED/source/"rare_disease_studies.jsonl.gz"
    if studies_path.exists():
        core.emit_records(source,"rare_disease_studies",core.read_records(studies_path),input_paths=[core.RAW/source,path],
            description="Union of generic rare/orphan/neurodevelopmental/inherited condition searches and exhaustively paged RareSource preferred disease-name OR batches. Membership records the complete batch term list; API response does not reveal which OR operand matched each study.")
    expected_names=[]
    for row in core.read_records(path):
        name=(row.get("Rare Disease Name") or "").strip()
        if name: expected_names.append(name)
    groups={}; bad_artifacts=[]; rawdir=core.RAW/source; manifest=core.manifest(source)
    for filename,entry in manifest.get("artifacts",{}).items():
        if not filename.startswith("disease-names-") or not filename.endswith(".json"): continue
        params=parse_qs(urlsplit(entry.get("url","")).query)
        conditions=params.get("query.cond",[])
        m=re.search(r"-page-(\d+)\.json$",filename)
        if not conditions or not m: continue
        condition=conditions[0]; index=int(m.group(1))
        group=groups.setdefault(condition,{"condition":condition,"terms":re.findall(r'"([^"]+)"',condition),"pages":{}})
        try:
            payload=_json(rawdir/filename); rows=payload.get("studies",[])
            ids=[r.get("protocolSection",{}).get("identificationModule",{}).get("nctId") for r in rows]
            group["pages"][index]={"rows":len(rows),"ids":[x for x in ids if x],"total":payload.get("totalCount"),
                                    "next_token":payload.get("nextPageToken"),"request_token":(params.get("pageToken") or [None])[0],"artifact":filename}
        except Exception as exc:
            bad_artifacts.append({"artifact":filename,"error":str(exc)[:300]})
            group["pages"][index]={"rows":0,"ids":[],"total":None,"next_token":None,"request_token":(params.get("pageToken") or [None])[0],"artifact":filename,"error":str(exc)[:300]}
    terminal=[]; query_details=[]; covered=set()
    for condition,g in groups.items():
        pages=g["pages"]; indexes=sorted(pages); rows=sum(x["rows"] for x in pages.values())
        ids=[i for p in indexes for i in pages[p]["ids"]]; distinct=len(set(ids))
        totals=[p["total"] for p in pages.values() if p["total"] is not None]
        total=totals[0] if totals else None; inconsistent=any(x!=total for x in totals)
        missing_pages=sorted(set(range(indexes[0],indexes[-1]+1))-set(indexes)) if indexes else []
        exhausted=bool(indexes) and not pages[indexes[-1]]["next_token"]
        token_chain=bool(indexes) and pages[indexes[0]]["request_token"] in (None,"") and all(
            pages[b]["request_token"]==pages[a]["next_token"] for a,b in zip(indexes,indexes[1:]))
        count_ok=total is not None and total==rows and total==distinct and not inconsistent
        detail={"condition":condition,"terms":g["terms"],"reported_total_count":total,"raw_returned_rows":rows,
                "distinct_nct_ids":distinct,"pages":indexes,"missing_pages":missing_pages,"next_token_exhausted":exhausted,
                "token_chain_matches":token_chain,"counts_match":count_ok,
                "status":"complete_terminal_leaf" if count_ok and not missing_pages and exhausted and token_chain else "incomplete"}
        if detail["status"]=="complete_terminal_leaf":
            terminal.append(detail); covered.update(_ctg_name_key(x) for x in g["terms"])
        query_details.append(detail)
    query_errors=[]
    manifest_coverage=manifest.get("disease_name_coverage",manifest.get("coverage",{}))
    for err in manifest_coverage.get("query_errors",[]):
        for name in err.get("terms",[]):
            query_errors.append({"name":name,"error":err.get("error"),"batch":err.get("batch"),"page":err.get("page")})
    fallback_rows=manifest.get("disease_name_fallbacks",[])
    fallback_covered={_ctg_name_key(x.get("preferred_name","")) for x in fallback_rows if x.get("status")=="complete"}
    fallback_errors=[x for x in fallback_rows if x.get("status")!="complete"]
    exact_covered=set(covered)
    missing_names=[n for n in expected_names if _ctg_name_key(n) not in exact_covered|fallback_covered]
    incomplete=[d for d in query_details if d["status"]!="complete_terminal_leaf"]
    unresolved_errors=[x for x in query_errors if _ctg_name_key(x["name"]) not in exact_covered|fallback_covered]
    result={"expected_preferred_names":len(expected_names),"unique_terminal_leaf_queries":len(terminal),
            "terminal_leaf_query_count_errors":len(incomplete),"terminal_leaf_queries":query_details,
            "names_covered_by_successful_terminal_queries":len({n for n in expected_names if _ctg_name_key(n) in exact_covered}),
            "names_covered_by_successful_fallbacks":len({n for n in expected_names if _ctg_name_key(n) in fallback_covered}),
            "names_with_explicit_query_errors":len({x["name"] for x in query_errors}),"names_unresolved":missing_names,
            "explicit_query_errors":query_errors,"unresolved_explicit_errors":unresolved_errors,
            "fallback_errors":fallback_errors,"bad_raw_artifacts":bad_artifacts,
            "complete_for_all_preferred_names":not missing_names and not incomplete and not bad_artifacts,
            "limitation":"A successful OR query verifies the complete terminal expression, not which operand matched each trial. Split parents never count as terminal coverage."}
    status=("complete_with_fallbacks" if query_errors and not missing_names and not incomplete and not bad_artifacts else
            ("complete" if not missing_names and not incomplete and not bad_artifacts else "partial_with_query_gaps"))
    core.update_manifest(source,status=status,
                         disease_name_expansion_audit=result)
    return result


def retry_ctg_preferred_name_errors(path=None, source="clinicaltrials_gov"):
    """Retry failed complex single-name CTG conditions with bounded, documented phrase fallbacks."""
    path=Path(path or core.PROCESSED/"raresource/diseases.jsonl.gz")
    manifest=core.manifest(source); coverage=manifest.get("disease_name_coverage",{})
    errors=coverage.get("query_errors",[]); names=sorted({n for e in errors for n in e.get("terms",[])})
    if not names: return []
    fallback_map={
        "Brain abnormalities-severe developmental delay-facial dysmorphism-intellectual disability syndrome due to MEF2C mutation": '"MEF2C mutation"',
        "Cognitive impairment - coarse facies - heart defects - obesity - pulmonary involvement - short stature - skeletal dysplasia syndrome": '"coarse facies" OR "skeletal dysplasia"',
        "Congenital adrenal insufficiency with 46, XY sex reversal OR 46,XY disorder of sex development-adrenal insufficiency due to CYP11A1 deficiency": '"CYP11A1 deficiency"',
        "Congenital anomalies of kidney and urinary tract syndrome with or without hearing loss, abnormal ears, or developmental delay": '"congenital anomalies of kidney"',
        "Developmental delay-language impairment-dopa responsive dystonia-parkinsonism syndrome due to a NR4A2 point mutation": '"NR4A2 mutation" OR "dopa responsive dystonia"',
        "Glycogen storage disease due to glycogen branching enzyme deficiency, childhood combined hepatic and myopathic form": '"glycogen branching enzyme"',
        "Intrauterine growth restriction-congenital multiple café-au-lait macules-increased sister chromatid exchange syndrome": '"cafe au lait macules" OR "sister chromatid exchange"',
        "NRXN1-related severe neurodevelopmental disorder-motor stereotypies-chronic constipation-sleep-wake cycle disturbance": 'NRXN1',
        "Severe combined immunodeficiency, autosomal recessive, T cell-negative, B cell-negative, NK cell-negative, due to adenosine deaminase deficiency": '"adenosine deaminase deficiency"',
        "Severe combined immunodeficiency, autosomal recessive, T cell-negative, B cell-negative, NK cell-positive": '"NK cell positive" OR "severe combined immunodeficiency"',
        "X-linked external auditory canal atresia-dilated internal auditory canal-facial dysmorphism syndrome": '"external auditory canal atresia"',
        "X-linked keloid scarring-reduced joint mobility-increased optic cup-to-disc ratio syndrome": '"keloid scarring" OR "optic cup to disc ratio"',
    }
    existing_path=core.PROCESSED/source/"rare_disease_studies.jsonl.gz"; studies={}
    for row in core.read_records(existing_path):
        ident=row.get("protocolSection",{}).get("identificationModule",{}).get("nctId")
        if ident: studies[ident]=row
    previous={x.get("preferred_name"):x for x in manifest.get("disease_name_fallbacks",[])}
    out=[]
    for name in names:
        condition=fallback_map.get(name)
        if not condition:
            out.append({"preferred_name":name,"status":"fallback_expression_unavailable"}); continue
        ident=hashlib.sha256((name+"|"+condition).encode()).hexdigest()[:12]
        token=None; page=0; seen=0; ids=set(); total=None; query_error=None
        while True:
            params={"query.cond":condition,"pageSize":1000,"format":"json","countTotal":"true"}
            if token: params["pageToken"]=token
            url=CTG_BASE+"?"+urlencode(params)
            try:
                raw=_get(source,url,f"disease-fallback-{ident}-page-{page:05d}.json","U.S. federal public registry data","API v2 phrase fallback")
                payload=_json(raw); total=int(payload.get("totalCount",0)); rows=payload.get("studies",[])
            except Exception as exc:
                query_error=str(exc)[:500]; break
            seen+=len(rows)
            for row in rows:
                ident_value=row.get("protocolSection",{}).get("identificationModule",{}).get("nctId")
                if not ident_value: continue
                ids.add(ident_value)
                previous_row=studies.get(ident_value,row)
                member={"query_set":"raresource_preferred_name_phrase_fallback","preferred_name":name,"query_condition":condition}
                memberships=previous_row.setdefault("query_membership",[])
                if member not in memberships: memberships.append(member)
                studies[ident_value]=previous_row
            page+=1; token=payload.get("nextPageToken")
            if not token: break
            time.sleep(.15)
        complete=(query_error is None and total is not None and seen==total and len(ids)==total and token is None)
        row={"preferred_name":name,"query_condition":condition,"reported_total_count":total,"raw_returned_rows":seen,
             "distinct_nct_ids":len(ids),"pages":page,"status":"complete" if complete else "query_error_or_count_mismatch"}
        if query_error: row["error"]=query_error
        previous[name]=row; out.append(row)
    core.emit_records(source,"rare_disease_studies",studies.values(),input_paths=[core.RAW/source,path],
        description="Union of generic CTG terms, exhaustively paged preferred-name queries, and explicitly labeled phrase fallbacks for complex rejected names.")
    core.update_manifest(source,status="in_progress",disease_name_fallbacks=list(previous.values()))
    audit_ctg_disease_names(path,source)
    return out


def harvest_ctg_disease_names(path=None, page_size=1000):
    """Expand ClinicalTrials.gov condition searches using RareSource preferred names."""
    source="clinicaltrials_gov"
    path=Path(path or core.PROCESSED/"raresource/diseases.jsonl.gz")
    if not path.exists(): raise FileNotFoundError(f"RareSource preferred-name dataset not found: {path}")
    existing_path=core.PROCESSED/source/"rare_disease_studies.jsonl.gz"
    if not existing_path.exists(): raise RuntimeError("Run the generic ClinicalTrials.gov harvest before disease-name expansion")
    studies={}
    for row in core.read_records(existing_path):
        ident=row.get("protocolSection",{}).get("identificationModule",{}).get("nctId")
        if ident: studies[ident]=row
    batch_stats=[]; query_errors=[]; pending=list(_disease_batches(path)); batch_count=0
    while pending:
        batch_count+=1; names=pending.pop(0)
        condition=_ctg_condition(names)
        condition_hash=hashlib.sha256(condition.encode()).hexdigest()[:12]
        token=None; page=0; seen=0
        while True:
            params={"query.cond":condition,"pageSize":page_size,"format":"json","countTotal":"true"}
            if token: params["pageToken"]=token
            url=CTG_BASE+"?"+urlencode(params)
            try:
                raw=_get(source,url,f"disease-names-{condition_hash}-page-{page:05d}.json","U.S. federal public registry data","API v2")
            except Exception as exc:
                if len(names)>1 and ("400 Client Error" in str(exc) or "Too complicated query" in str(exc)):
                    midpoint=len(names)//2
                    pending.insert(0,names[midpoint:]); pending.insert(0,names[:midpoint])
                    break
                query_errors.append({"batch":batch_count,"page":page,"terms":names,"error":str(exc)[:1000]})
                break
            payload=_json(raw); rows=payload.get("studies",[])
            if not rows: break
            for row in rows:
                ident=row.get("protocolSection",{}).get("identificationModule",{}).get("nctId")
                if not ident: continue
                previous=studies.get(ident)
                if previous: row=previous
                memberships=row.setdefault("query_membership",[])
                entry={"query_set":"raresource_preferred_names_or_batch","batch":batch_count,"terms":names}
                if entry not in memberships: memberships.append(entry)
                studies[ident]=row
            seen+=len(rows); page+=1; token=payload.get("nextPageToken")
            if not token: break
            time.sleep(.15)
        batch_stats.append({"batch":batch_count,"terms":len(names),"records_seen":seen,"pages":page,"query_hash":condition_hash})
        time.sleep(.15)
    if not studies: raise RuntimeError("No ClinicalTrials.gov studies remain after RareSource query expansion")
    out=core.emit_records(source,"rare_disease_studies",studies.values(),input_paths=[core.RAW/source,path],
        description="Union of generic rare/orphan/neurodevelopmental/inherited condition searches and exhaustively paged RareSource preferred disease-name OR batches. Membership records the complete batch term list; API response does not reveal which OR operand matched each study.")
    core.update_manifest(source,status="complete_with_query_errors" if query_errors else "complete",disease_name_source=str(path.relative_to(core.ROOT)),disease_name_coverage={"preferred_names":sum(len(x) for x in _disease_batches(path)),"batches":batch_count,"batches_detail":batch_stats,"query_errors":query_errors,"unique_studies_after_union":len(studies),"limitation":"A study returned for an OR batch is linked to that batch's full list of candidate names because the API does not identify which operand matched. Source query recall remains spelling and condition-index dependent."})
    audit_ctg_disease_names(path,source)
    return out


def harvest_reporter(start_year=1985, end_year=None, page_size=500):
    source="nih_reporter"; end_year=end_year or date.today().year; unique={}; years=[]; query_errors=[]
    terms=("rare disease","rare diseases","orphan disease","orphan diseases")
    fields=("PROJECTTITLE","ABSTRACTTEXT","TERMS")
    for year in range(start_year,end_year+1):
        search_stats=[]
        for field in fields:
            for term in terms:
                offset=0; total=None; seen=0; query_keys=set(); query_id=f"{year}/{field}/{term}"
                while total is None or offset < total:
                    body={"criteria":{"advanced_text_search":{"operator":"and","search_field":field,"search_text":term},"fiscal_years":[year]},"offset":offset,"limit":page_size}
                    filename=f"fy-{year}-{field}-{term.replace(' ','-')}-offset-{offset:07d}.json"
                    try:
                        path=core.download(source,REPORTER_URL,filename,license_name="NIH RePORTER public project metadata",version="v2",method="POST",json_body=body)
                        payload=_json(path); meta=payload.get("meta",{}); rows=payload.get("results",[])
                    except Exception as exc:
                        query_errors.append({"query":query_id,"offset":offset,"expected":total,"seen":seen,"error":str(exc)[:500]})
                        break
                    if total is None: total=int(meta.get("total",0))
                    if total>12000:
                        query_errors.append({"query":query_id,"expected":total,"seen":seen,"error":"exceeds documented offset range; query partition required"})
                        break
                    if not rows:
                        if total is not None and offset<total: query_errors.append({"query":query_id,"expected":total,"seen":seen,"error":"empty page before reported total"})
                        break
                    for row in rows:
                        key=(row.get("appl_id"),row.get("subproject_id"),row.get("fiscal_year"))
                        query_keys.add(key)
                        unique[key]=row
                    seen+=len(rows); offset+=len(rows)
                    if len(rows)<page_size:
                        if total is not None and offset<total: query_errors.append({"query":query_id,"expected":total,"seen":seen,"error":"short page before reported total"})
                        break
                    time.sleep(.15)
                if total is None: query_errors.append({"query":query_id,"expected":None,"seen":seen,"error":"missing total count"})
                elif seen!=total: query_errors.append({"query":query_id,"expected":total,"seen":seen,"error":"record count does not match reported total"})
                if total is not None and len(query_keys)!=total: query_errors.append({"query":query_id,"expected_unique":total,"unique_keys":len(query_keys),"error":"unique application-key count does not match reported total"})
                search_stats.append({"field":field,"term":term,"reported_total":total,"records_seen":seen,"unique_keys":len(query_keys)})
        years.append({"fiscal_year":year,"searches":search_stats})
    if not unique: raise RuntimeError("RePORTER returned no projects")
    out=core.emit_records(source,"rare_disease_projects",unique.values(),input_paths=[core.RAW/source],description=f"NIH RePORTER v2 PROJECTTITLE/ABSTRACTTEXT/TERMS query for rare/orphan disease variants; FY {start_year}-{end_year}.")
    core.update_manifest(source,status="complete_with_query_errors" if query_errors else "complete",query={"fields":fields,"terms":terms},coverage={"unique_application_fy_subproject_keys":len(unique),"fiscal_years":years,"query_errors":query_errors,"limitation":"RePORTER text search is broad but not guaranteed to cover disease-specific names absent from matched project text."})
    return out


def harvest_reporter_grin(start_year=1985,end_year=None,page_size=500):
    """Acquire focused NIH funding metadata matching GRIN2A/B subunit aliases."""
    source="nih_reporter"; end_year=end_year or date.today().year
    aliases=("GRIN2A","GRIN2B","GluN2A","GluN2B","NR2A","NR2B")
    search_text=" OR ".join(aliases); unique={}; fiscal=[]; errors=[]
    for year in range(start_year,end_year+1):
        offset=0; total=None; seen=0; keys=set()
        while total is None or offset<total:
            body={"criteria":{"advanced_text_search":{"operator":"or","search_field":"All","search_text":search_text},"fiscal_years":[year]},"offset":offset,"limit":page_size}
            try:
                path=core.download(source,REPORTER_URL,f"grin-fy-{year}-offset-{offset:07d}.json",license_name="NIH RePORTER public project metadata",version="v2",method="POST",json_body=body)
                payload=_json(path); meta=payload.get("meta",{}); rows=payload.get("results",[])
            except Exception as exc:
                errors.append({"fiscal_year":year,"offset":offset,"expected":total,"seen":seen,"error":str(exc)[:500]})
                break
            if total is None: total=int(meta.get("total",0))
            if total>12000:
                errors.append({"fiscal_year":year,"expected":total,"seen":seen,"error":"FY query exceeds documented offset range; must split alias groups"}); break
            if not rows:
                if offset<total: errors.append({"fiscal_year":year,"expected":total,"seen":seen,"error":"empty page before reported total"})
                break
            for row in rows:
                key=(row.get("appl_id"),row.get("subproject_id"),row.get("fiscal_year")); keys.add(key)
                row.setdefault("query_membership",[]).append({"query_set":"GRIN subunit aliases","terms":list(aliases),"fiscal_year":year})
                unique[key]=row
            seen+=len(rows); offset+=len(rows)
            if len(rows)<page_size:
                if offset<total: errors.append({"fiscal_year":year,"expected":total,"seen":seen,"error":"short page before reported total"})
                break
            time.sleep(.15)
        if total is not None and (seen!=total or len(keys)!=total):
            errors.append({"fiscal_year":year,"expected":total,"seen":seen,"unique_application_keys":len(keys),"error":"count/unique key mismatch"})
        fiscal.append({"fiscal_year":year,"reported_total":total,"records_seen":seen,"unique_application_keys":len(keys)})
    if not unique: raise RuntimeError("Focused RePORTER GRIN2A/B query returned no records")
    out=core.emit_records(source,"grin_projects",unique.values(),input_paths=[core.RAW/source],
        description=f"Focused NIH RePORTER v2 all-fields text search: {search_text}; fiscal years {start_year}-{end_year}.")
    broad_errors=(core.manifest(source).get("broad_cache_audit",{}).get("query_errors",[])
                  or core.manifest(source).get("coverage",{}).get("query_errors",[]))
    core.update_manifest(source,status="complete_with_query_errors" if errors or broad_errors else "complete",grin_query=search_text,grin_coverage={"aliases":list(aliases),"unique_project_application_fy_subprojects":len(unique),"fiscal_years":fiscal,"query_errors":errors,"limitation":"Text search is source-indexed and alias-based; it does not imply project relevance or experimental validation."})
    return out


def audit_reporter_cache():
    """Offline integrity audit of all cached RePORTER query pages in the manifest."""
    source="nih_reporter"; m=core.manifest(source); groups={}; rawdir=core.RAW/source
    broad_records={}; grin_records={}
    for filename,entry in m.get("artifacts",{}).items():
        body=entry.get("request_body")
        if not isinstance(body,dict) or not filename.endswith(".json"): continue
        if body.get("sort_field"):
            continue
        criteria=body.get("criteria",{}); years=criteria.get("fiscal_years",[])
        search=criteria.get("advanced_text_search",{})
        if not years or not search: continue
        key=(years[0],search.get("search_field"),search.get("search_text"),search.get("operator"))
        group=groups.setdefault(key,{"expected":None,"rows":0,"keys":set(),"offsets":[]})
        payload=_json(rawdir/filename); meta=payload.get("meta",{}); rows=payload.get("results",[])
        total=int(meta.get("total",0))
        if group["expected"] is not None and group["expected"]!=total:
            group["inconsistent_totals"]=[group["expected"],total]
        group["expected"]=total; group["rows"]+=len(rows); group["offsets"].append(int(body.get("offset",0)))
        for original in rows:
            row=dict(original); app_key=(row.get("appl_id"),row.get("subproject_id"),row.get("fiscal_year"))
            group["keys"].add(app_key)
            member={"search_field":search.get("search_field"),"search_text":search.get("search_text"),
                    "operator":search.get("operator"),"fiscal_year":years[0]}
            dest=grin_records if search.get("search_field")=="All" else broad_records
            previous=dest.get(app_key)
            if previous:
                if member not in previous.setdefault("query_membership",[]): previous["query_membership"].append(member)
            else:
                row["query_membership"]=[member]; dest[app_key]=row
    for filename,entry in m.get("artifacts",{}).items():
        body=entry.get("request_body")
        if not isinstance(body,dict) or not body.get("sort_field") or not filename.endswith(".json"): continue
        criteria=body.get("criteria",{}); years=criteria.get("fiscal_years",[])
        search=criteria.get("advanced_text_search",{})
        if not years or not search: continue
        key=(years[0],search.get("search_field"),search.get("search_text"),search.get("operator"))
        group=groups.setdefault(key,{"expected":None,"rows":0,"keys":set(),"offsets":[]})
        check=group.setdefault("recheck",{"expected":None,"rows":0,"keys":set(),"offsets":[]})
        payload=_json(rawdir/filename); meta=payload.get("meta",{}); rows=payload.get("results",[])
        total=int(meta.get("total",0)); check["expected"]=total; check["rows"]+=len(rows); check["offsets"].append(int(body.get("offset",0)))
        for original in rows:
            row=dict(original); app_key=(row.get("appl_id"),row.get("subproject_id"),row.get("fiscal_year")); check["keys"].add(app_key)
            member={"query_set":"NIH duplicate-partition sort recheck","search_field":search.get("search_field"),"search_text":search.get("search_text"),
                    "operator":search.get("operator"),"fiscal_year":years[0],"sort_field":body.get("sort_field"),"sort_order":body.get("sort_order")}
            dest=grin_records if search.get("search_field")=="All" else broad_records
            previous=dest.get(app_key)
            if previous:
                if member not in previous.setdefault("query_membership",[]): previous["query_membership"].append(member)
            else:
                row["query_membership"]=[member]; dest[app_key]=row
    audit=[]
    for (year,field,term,operator),g in groups.items():
        row={"fiscal_year":year,"field":field,"term":term,"operator":operator,"reported_total":g["expected"],"records_seen":g["rows"],
             "unique_application_keys":len(g["keys"]),"offsets":sorted(g["offsets"])}
        check=g.get("recheck")
        if check:
            row["sort_recheck"]={"reported_total":check["expected"],"records_seen":check["rows"],"unique_application_keys":len(check["keys"]),"offsets":sorted(check["offsets"]),
                                 "sort_field":"project_start_date","sort_order":"asc"}
            row["recheck_recovered"]=(check["expected"]==check["rows"]==len(check["keys"]))
        if "inconsistent_totals" in g: row["inconsistent_totals"]=g["inconsistent_totals"]
        if (g["rows"]!=g["expected"] or len(g["keys"])!=g["expected"] or "inconsistent_totals" in g) and not row.get("recheck_recovered"):
            row["error"]="reported total, row count, or unique-key count mismatch"
        elif row.get("recheck_recovered"):
            row["baseline_duplicate_key_discrepancy"]={"records_seen":g["rows"],"unique_application_keys":len(g["keys"]),"reported_total":g["expected"]}
        audit.append(row)
    errors=[x for x in audit if x.get("error")]
    if broad_records:
        core.emit_records(source,"rare_disease_projects",broad_records.values(),input_paths=[rawdir],
            description="Deduplicated NIH RePORTER public projects for rare/orphan disease title, abstract, and terms searches. Cached request bodies preserve query membership; failed/incomplete queries remain explicit in the manifest audit.")
    if grin_records:
        core.emit_records(source,"grin_projects",grin_records.values(),input_paths=[rawdir],
            description="Deduplicated NIH RePORTER projects matching focused GRIN2A/GRIN2B and GluN2A/B/NR2A/B aliases; query membership is retained per fiscal-year request.")
    focused_errors=m.get("grin_coverage",{}).get("query_errors",[])
    core.update_manifest(source,status="complete_with_query_errors" if errors or focused_errors else "complete",broad_cache_audit={"queries":len(audit),"query_errors":errors,"queries_detail":audit,"all_cached_queries_complete":not errors})
    return audit


def retry_reporter_duplicate_queries(page_size=500):
    """Re-traverse only cached NIH partitions whose row count matched but keys did not."""
    source="nih_reporter"; manifest=core.manifest(source)
    prior=manifest.get("broad_cache_audit",{}).get("queries_detail",[])
    targets=[x for x in prior if x.get("records_seen")==x.get("reported_total")
             and x.get("unique_application_keys")!=x.get("reported_total")]
    results=[]; rawdir=core.RAW/source; rows_by_key={}
    for row in core.read_records(core.PROCESSED/source/"rare_disease_projects.jsonl.gz"):
        rows_by_key[(row.get("appl_id"),row.get("subproject_id"),row.get("fiscal_year"))]=row
    for target in targets:
        year=int(target["fiscal_year"]); field=target["field"]; term=target["term"]
        offset=0; total=None; seen=0; keys=set(); rows_all=[]; error=None
        while total is None or offset<total:
            body={"criteria":{"advanced_text_search":{"operator":"and","search_field":field,"search_text":term},"fiscal_years":[year]},
                  "offset":offset,"limit":page_size,"sort_field":"project_start_date","sort_order":"asc"}
            safe_field=re.sub(r"[^A-Za-z0-9]+","-",field).strip("-")
            safe_term=re.sub(r"[^A-Za-z0-9]+","-",term).strip("-")
            filename=f"recheck-fy-{year}-{safe_field}-{safe_term}-start-date-asc-offset-{offset:07d}.json"
            try:
                path=core.download(source,REPORTER_URL,filename,license_name="NIH RePORTER public project metadata",version="v2",method="POST",json_body=body)
                payload=_json(path); meta=payload.get("meta",{}); rows=payload.get("results",[])
            except Exception as exc:
                error=str(exc)[:500]; break
            if total is None: total=int(meta.get("total",0))
            if not rows:
                if offset<total: error="empty page before reported total"
                break
            for row in rows:
                keys.add((row.get("appl_id"),row.get("subproject_id"),row.get("fiscal_year")))
                rows_all.append(row)
            seen+=len(rows); offset+=len(rows)
            if len(rows)<page_size and offset<total: error="short page before reported total"; break
            if offset<total: time.sleep(.2)
        complete=error is None and total==seen==len(keys)
        results.append({"fiscal_year":year,"field":field,"term":term,"reported_total":total,"records_seen":seen,
                        "unique_application_keys":len(keys),"complete":complete,"error":error,
                        "sort_field":"project_start_date","sort_order":"asc"})
        if rows_all:
            # Cached re-traversals remain separate audit artifacts; their rows also fill gaps
            # in the emitted deduplicated corpus and retain explicit recheck provenance.
            for row in rows_all:
                member={"query_set":"NIH duplicate-partition sort recheck","search_field":field,"search_text":term,
                        "operator":"and","fiscal_year":year,"sort_field":"project_start_date","sort_order":"asc"}
                row.setdefault("query_membership",[]).append(member)
                rawkey=(row.get("appl_id"),row.get("subproject_id"),row.get("fiscal_year"))
                rows_by_key[rawkey]=row
    core.update_manifest(source,status="in_progress",reporter_duplicate_rechecks=results)
    if rows_by_key:
        core.emit_records(source,"rare_disease_projects",rows_by_key.values(),input_paths=[rawdir],
                          description="NIH RePORTER broad rare/orphan disease corpus with separately labeled stable-sort rechecks for duplicate-key discrepancies.")
    return results


def _month_intervals(start=date(1990,1,1), end=None):
    end=end or date.today()
    y,m=start.year,start.month
    while date(y,m,1)<=end:
        last=calendar.monthrange(y,m)[1]; hi=min(end,date(y,m,last))
        yield date(y,m,1),hi
        if m==12:y,m=y+1,1
        else:y,m=y,m+1


def harvest_preprints():
    """Harvest search-matched preprint metadata from Europe PMC's PPR index."""
    source="europe_pmc_preprints"
    query='SRC:PPR AND (TITLE_ABS:"rare disease" OR TITLE_ABS:"orphan disease" OR TITLE_ABS:"neurodevelopmental disorder" OR TITLE_ABS:"inherited disorder")'
    cursor="*"; records={}; page=0; total=None
    while True:
        params={"query":query,"format":"json","resultType":"core","pageSize":1000,"cursorMark":cursor}
        url="https://www.ebi.ac.uk/europepmc/webservices/rest/search?"+urlencode(params)
        path=_get(source,url,f"page-{page:05d}.json","Europe PMC preprint metadata; underlying server license controls full text","REST 6.9")
        payload=_json(path); total=int(payload.get("hitCount",0)); rows=payload.get("resultList",{}).get("result",[])
        for row in rows:
            ident=row.get("id")
            if ident:
                doi=row.get("doi")
                row["version_id"]=(doi.rsplit("/",1)[-1] if doi and "/v" in doi else None)
                row["preprint_server"]=next((urlsplit(x.get("url","")).hostname for x in row.get("fullTextUrlList",{}).get("fullTextUrl",[]) if urlsplit(x.get("url","")).hostname and any(host in urlsplit(x.get("url","")).hostname for host in ("biorxiv.org","medrxiv.org"))),None)
                records[ident]=row
        next_cursor=payload.get("nextCursorMark")
        page+=1
        if not rows or not next_cursor or next_cursor==cursor: break
        cursor=next_cursor
        if len(records)>=total: break
        time.sleep(.15)
    if not records: raise RuntimeError("Europe PMC preprint search returned no records")
    out=core.emit_records(source,"rare_disease_related_preprints",records.values(),input_paths=[core.RAW/source],
        description=f"Europe PMC PPR full-metadata search: {query}. Current indexed record versions only; original server is retained only when explicit in a repository URL and otherwise left unknown.")
    core.update_manifest(source,status="complete",query=query,coverage={"unique_preprint_ids":len(records),"reported_hit_count":total,"pages":page,
        "limitation":"Searches title/abstract wording, so disease-name-only preprints may be missed. Europe PMC indexes current preprint records; preserve PPR IDs and DOI/version strings where supplied. The source does not always expose the originating server; none is inferred from DOI alone. Full text remains governed by each server's license."})
    return out


def harvest_pmc_linked(pubmed_path=None, source="pmc_linked_oa", dataset_name="licensed_full_text"):
    """Use Europe PMC core metadata to license-gate linked PMC full text."""
    pubmed_path=Path(pubmed_path or core.PROCESSED/"pubmed/rare_disease_citations.jsonl.gz")
    if not pubmed_path.exists(): raise FileNotFoundError(f"PubMed citation dataset not found: {pubmed_path}")
    linked={}; missing=0; excluded_nonfocus=0; scanned_citations=0; missing_citations=[]
    for article in core.read_records(pubmed_path):
        scanned_citations+=1
        pmid=article.get("pmid")
        pmcids=[(x.get("value") or "").upper() for x in article.get("article_ids",[]) if (x.get("type") or "").lower() in {"pmc","pmcid"}]
        pmcids=[("PMC"+x if x.isdigit() else x) for x in pmcids]
        if source=="pmc_grin_oa":
            evidence=" ".join([article.get("title") or "",*[(x.get("text") or "") for x in article.get("abstract_sections",[])],
                               *[(x.get("descriptor") or "") for x in article.get("mesh_headings",[])]])
            if pmid not in GRIN_FULLTEXT_PMIDS and not GRIN_FULLTEXT_PMCIDS.intersection(pmcids) and not GRIN_FULLTEXT_RE.search(evidence):
                excluded_nonfocus+=1; continue
        found=False
        for pmcid in pmcids:
            if pmcid:
                if pmcid.startswith("PMC") and pmcid[3:].isdigit():
                    linked.setdefault(pmcid,[]).append(pmid); found=True
        if not found:
            missing+=1
            missing_citations.append({"pmid":pmid,"title":article.get("title"),
                                      "doi":next((x.get("value") for x in article.get("article_ids",[]) if x.get("type")=="doi"),None),
                                      "status":"no_linked_pmc_identifier"})
    if not linked: raise RuntimeError("PubMed corpus contains no PMC identifiers; no licensing status can be asserted")
    # Europe PMC's core endpoint accepts an OR of PMCID fields and exposes the
    # article's isOpenAccess and license values, avoiding one OAI request per ID.
    ids=sorted(linked); metadata={}; exact_batches=[]; metadata_errors=[]; batch_size=40
    endpoint="https://www.ebi.ac.uk/europepmc/webservices/rest/search"
    for offset in range(0,len(ids),batch_size):
        batch=ids[offset:offset+batch_size]
        query="PMCID:("+" OR ".join(batch)+")"
        params={"query":query,"format":"json","resultType":"core","pageSize":1000,"cursorMark":"*"}
        cursor="*"; returned={}; pages=0; hit_count=None
        while True:
            params["cursorMark"]=cursor
            url=endpoint+"?"+urlencode(params)
            import hashlib
            key=hashlib.sha256((query+"|"+cursor).encode()).hexdigest()[:20]
            try:
                path=_get(source,url,f"epmc-license-{key}.json","Europe PMC core metadata; article license fields retained","current")
                payload=_json(path); hit_count=int(payload.get("hitCount",0))
                rows=payload.get("resultList",{}).get("result",[])
                for row in rows:
                    pmcid=(row.get("pmcid") or "").upper()
                    if pmcid: returned[pmcid]=row
                pages+=1
                next_cursor=payload.get("nextCursorMark")
                if not rows or not next_cursor or next_cursor==cursor: break
                cursor=next_cursor
            except Exception as exc:
                metadata_errors.append({"requested_pmcids":batch,"status":"metadata_fetch_error","error":str(exc)[:500]})
                break
        expected=set(batch); actual=set(returned)
        exact_batches.append({"requested":len(expected),"reported_hits":hit_count,"returned_unique_pmcids":len(actual),
                             "missing_pmcids":sorted(expected-actual),"unexpected_pmcids":sorted(actual-expected),"pages":pages})
        metadata.update(returned)
    eligible={}; queued=[]; focus_linked={}
    for pmcid,pmids in linked.items():
        row=metadata.get(pmcid)
        if not row:
            queued.append({"pmcid":pmcid,"pmids":pmids,"status":"metadata_missing_from_europe_pmc"}); continue
        license_id=(row.get("license") or "").strip().lower()
        # CC BY, CC BY-SA, CC BY-NC, CC BY-NC-SA and CC0 permit the intended
        # attribution-preserving research copy; ND licenses remain review-only.
        compatible=license_id in {"cc by","cc by-sa","cc by-nc","cc by-nc-sa","cc0"}
        item={"pmcid":pmcid,"pmids":pmids,"is_open_access":row.get("isOpenAccess"),
              "license":row.get("license"),"europe_pmc_source":row.get("source"),"title":row.get("title"),"doi":row.get("doi")}
        if compatible:
            eligible[pmcid]=item
        else:
            item["status"]=("license_unknown" if not license_id else
                            ("license_no_derivatives_review" if license_id in {"cc by-nc-nd","cc by-nc-nd 4.0"} else "license_other_incompatible"))
            queued.append(item)
    # Keep metadata mapping to original IDs and PMID membership for audit.
    core.emit_records(source,"license_metadata",(
        {"pmcid":pid,"pmids":linked.get(pid,[]),"is_open_access":row.get("isOpenAccess"),"license":row.get("license"),
         "europe_pmc_source":row.get("source"),"pmid":row.get("pmid"),"doi":row.get("doi"),"title":row.get("title"),
         "raw_metadata":row} for pid,row in sorted(metadata.items())),input_paths=[pubmed_path,core.RAW/source],
        description="Europe PMC core metadata queried by exact PMCID groups. isOpenAccess and source license identifiers retained; no license inferred from PMC membership.")
    fulltexts=[]; retrieval_queue=[]
    progress_path=core.RAW/source/"fulltext_progress.json"
    completed=[]; ncbi_request_lock=threading.Lock(); last_ncbi_request=[0.0]
    prior_progress={}
    if progress_path.exists():
        try: prior_progress=json.loads(progress_path.read_text(encoding="utf-8"))
        except Exception: prior_progress={}
    prior_errors=prior_progress.get("errors",[])
    prior_completed={row.get("pmcid"):row for row in prior_progress.get("completed",[]) if row.get("pmcid")}
    prior_500=sum("500 Server Error" in x.get("error","") for x in prior_errors)
    epmc_fulltext_systemic_failure=prior_500>=3 and prior_500>=len(prior_errors)/2
    def fetch_epmc_fulltext(pmcid,item):
        epmc_url=f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
        fulltext_source="europe_pmc_fullTextXML"; url=epmc_url; epmc_error=None
        try:
            if epmc_fulltext_systemic_failure or prior_completed.get(pmcid,{}).get("fulltext_source")=="ncbi_pmc_efetch":
                raise RuntimeError("Europe PMC fullTextXML showed repeated HTTP 500 responses in prior bounded probes")
            path=_get(source,epmc_url,f"licensed-jats-{pmcid}.xml","Europe PMC full text; compatible explicit CC license verified in core metadata",item["license"])
            article=ET.parse(path).getroot()
        except Exception as exc:
            epmc_error=str(exc)[:500]
            # Switch away from a repeatedly failing EPMC XML route to the
            # official NCBI EFetch API; license verification still precedes it.
            ncbi_url="https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?"+urlencode({"db":"pmc","id":pmcid[3:],"retmode":"xml","tool":"LIT-knowledge-graph"})
            try:
                url=ncbi_url
                cached_ncbi=core.RAW/source/f"licensed-jats-ncbi-{pmcid}.xml"
                if cached_ncbi.exists():
                    path=cached_ncbi
                else:
                    with ncbi_request_lock:
                        delay=.51-(time.monotonic()-last_ncbi_request[0])
                        if delay>0: time.sleep(delay)
                        path=_get(source,ncbi_url,f"licensed-jats-ncbi-{pmcid}.xml","NCBI PMC EFetch full text; compatible explicit CC license verified in Europe PMC core",item["license"])
                        last_ncbi_request[0]=time.monotonic()
                fulltext_source="ncbi_pmc_efetch"
                article=ET.parse(path).getroot()
            except Exception as ncbi_exc:
                return None,{**item,"status":"fulltext_fetch_error","europe_pmc_endpoint":epmc_url,
                             "europe_pmc_error":epmc_error,"ncbi_efetch_endpoint":ncbi_url,"error":str(ncbi_exc)[:500]}
        try:
            validation_error,returned_pmcid=_pmc_jats_error(article,pmcid)
            if validation_error:
                return None,{**item,"status":validation_error,"returned_pmcid":returned_pmcid,
                             "fulltext_source":fulltext_source,"fulltext_endpoint":url,"europe_pmc_endpoint":epmc_url}
            item.update({"body_license":[item["license"]],"supplementary_links":[
                {"href":el.get("{http://www.w3.org/1999/xlink}href"),"label":el.get("{http://www.w3.org/1999/xlink}title"),"article_license":item["license"]}
                for el in article.findall(".//supplementary-material") if el.get("{http://www.w3.org/1999/xlink}href")],
                "fulltext_source":fulltext_source,"fulltext_endpoint":url,
                "europe_pmc_error":epmc_error,"returned_pmcid":returned_pmcid,
                "jats_xml":ET.tostring(article,encoding="unicode")})
            return item,None
        except Exception as exc:
            return None,{**item,"status":"fulltext_parse_error","fulltext_source":fulltext_source,
                         "fulltext_endpoint":url,"europe_pmc_endpoint":epmc_url,"error":str(exc)[:500]}
    core.atomic_json(progress_path,{"expected_compatible_pmcids":sorted(eligible),"completed":[],"errors":[],"status":"in_progress"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures={pool.submit(fetch_epmc_fulltext,pmcid,item):(pmcid,item) for pmcid,item in eligible.items()}
        for future in as_completed(futures):
            pmcid,item=futures[future]
            try: record,error=future.result()
            except Exception as exc: record,error=None,{**item,"status":"fulltext_fetch_error","error":str(exc)[:500]}
            if record is not None: fulltexts.append(record)
            if error is not None: retrieval_queue.append(error)
            completed.append({"pmcid":pmcid,"status":"downloaded" if record is not None else error["status"],
                              "fulltext_source":record.get("fulltext_source") if record else error.get("fulltext_source"),
                              "endpoint":record.get("fulltext_endpoint") if record else error.get("fulltext_endpoint",error.get("ncbi_efetch_endpoint",error.get("europe_pmc_endpoint"))),
                              "license":item.get("license"),"error":error.get("error") if error else None})
            core.atomic_json(progress_path,{"expected_compatible_pmcids":sorted(eligible),"completed":completed,
                                            "errors":retrieval_queue,"downloaded_jats_records":len(fulltexts),"status":"in_progress"})
    if fulltexts:
        core.emit_records(source,dataset_name,fulltexts,input_paths=[pubmed_path,core.RAW/source],
            description="Europe PMC JATS fetched only after core metadata exposed an explicit compatible Creative Commons license identifier.")
    if queued:
        core.emit_records(source,"rights_review_queue",queued,input_paths=[pubmed_path,core.RAW/source],
            description="Linked PMC identifiers lacking an explicit compatible license identifier in Europe PMC core metadata. No full text fetched for these records.")
    if missing_citations:
        core.emit_records(source,"no_pmcid_queue",missing_citations,input_paths=[pubmed_path],
            description="Focused PubMed citations without a primary-article PMCID in PubmedData/ArticleIdList; citation metadata is retained, but no PMC full-text license lookup is possible.")
    if retrieval_queue:
        core.emit_records(source,"fulltext_retry_queue",retrieval_queue,input_paths=[pubmed_path,core.RAW/source],description="Europe PMC full-text fetch or identity errors for records with an explicit compatible license.")
    has_errors=bool(metadata_errors or retrieval_queue or any(x["missing_pmcids"] or x["unexpected_pmcids"] or x["reported_hits"]!=x["returned_unique_pmcids"] for x in exact_batches))
    license_counts=Counter((row.get("license") or "missing").strip().lower() for row in metadata.values())
    queue_counts=Counter(row.get("status") for row in queued)
    coverage={"pubmed_citations_scanned":scanned_citations,"focus_citations_excluded":excluded_nonfocus,"linked_articles_with_pmcid":len(linked),
        "metadata_pmcids_expected":len(linked),"metadata_pmcids_returned":len(metadata),"metadata_exact_id_set_match":set(linked)==set(metadata),
        "metadata_pmcids_missing":len(set(linked)-set(metadata)),"metadata_batches":exact_batches,"metadata_errors":metadata_errors,"compatible_license_candidates":len(eligible),
        "license_counts":dict(sorted(license_counts.items())),"rights_queue_status_counts":dict(sorted(queue_counts.items())),
        "all_656_target_accounting":{"expected_linked_pmcs":len(linked),"metadata_returned":len(metadata),
            "eligible_explicit_licenses":len(eligible),"queued_metadata_missing":queue_counts.get("metadata_missing_from_europe_pmc",0),
            "queued_unknown_license":queue_counts.get("license_unknown",0),"queued_nd_license":queue_counts.get("license_no_derivatives_review",0),
            "queued_other_incompatible_license":queue_counts.get("license_other_incompatible",0),
            "partition_sum":len(eligible)+queue_counts.get("metadata_missing_from_europe_pmc",0)+queue_counts.get("license_unknown",0)+
                queue_counts.get("license_no_derivatives_review",0)+queue_counts.get("license_other_incompatible",0)},
        "downloaded_jats_records":len(fulltexts),"queued_for_rights_review":len(queued),"queued_for_fetch_retry":len(retrieval_queue),
        "citations_without_pmcid":missing,
        "limitation":"The corpus is limited to PubMed-linked PMCIDs in the declared focus query. All returned source-provided CC BY, CC BY-SA, CC BY-NC, CC BY-NC-SA, and CC0 identifiers are eligible for research-copy retrieval; the noncommercial restriction is retained on each record. CC BY-NC-ND is excluded from copying and queued separately. Missing/unknown and non-CC licenses are separately queued. Supplement links are recorded; assets are not fetched unless separately rights-verified."}
    if source=="pmc_grin_oa": coverage["focused_scope"]={"pmids":sorted(GRIN_FULLTEXT_PMIDS),"pmcids":sorted(GRIN_FULLTEXT_PMCIDS),"title_abstract_mesh_regex":GRIN_FULLTEXT_RE.pattern}
    status="partial_fulltext_retrieval" if retrieval_queue else ("partial_metadata" if has_errors else ("complete_with_rights_queue" if queued else "complete"))
    core.atomic_json(progress_path,{"expected_compatible_pmcids":sorted(eligible),"completed":completed,"errors":retrieval_queue,
                                    "downloaded_jats_records":len(fulltexts),"status":status})
    core.update_manifest(source,status=status,coverage=coverage)
    return len(fulltexts),len(queued)


def retry_pmc_html_fulltext(source="pmc_grin_oa"):
    """Try one official PMC HTML page for each licensed target whose XML lacked a body."""
    progress_path=core.RAW/source/"fulltext_progress.json"
    progress=json.loads(progress_path.read_text(encoding="utf-8"))
    failures=[row for row in progress.get("errors",[]) if row.get("status")=="fulltext_body_missing"]
    if not failures:
        return {"eligible_targets":0,"recovered_ids":[],"unavailable_ids":[]}
    licensed={row.get("pmcid"):row for row in core.read_records(core.PROCESSED/source/"license_metadata.jsonl.gz")}
    reuse_root=core.RAW/"grin_primary_pages"
    html_records=[]; statuses=[]
    for index,item in enumerate(failures):
        pmcid=item["pmcid"]
        metadata=licensed.get(pmcid,{})
        license_id=(metadata.get("license") or item.get("license") or "").strip().lower()
        if license_id not in {"cc by","cc by-sa","cc by-nc","cc by-nc-sa","cc0"}:
            statuses.append({"pmcid":pmcid,"status":"html_fallback_skipped_license_not_eligible","license":license_id or None})
            continue
        reuse_path=reuse_root/(pmcid+".html")
        url=f"https://pmc.ncbi.nlm.nih.gov/articles/{pmcid}/"
        try:
            if reuse_path.exists():
                html=reuse_path.read_text(encoding="utf-8",errors="replace")
                provenance={"html_endpoint":url,"html_path":str(reuse_path.relative_to(core.ROOT)),
                            "retrieval_source":"reused_verified_grin_primary_pages","raw_artifact_owned_by":"grin_primary_pages"}
            else:
                artifact=_get(source,url,f"html-fallback-{pmcid}.html",
                              "Explicit compatible license recorded in Europe PMC core metadata; PMC official article HTML snapshot",license_id)
                html=artifact.read_text(encoding="utf-8",errors="replace")
                provenance={"html_endpoint":url,"html_path":str(artifact.relative_to(core.ROOT)),
                            "retrieval_source":"official_pmc_article_html"}
            validation=_pmc_html_validation(html,pmcid)
            status={"pmcid":pmcid,"license":license_id,**provenance,
                    "html_status":validation["status"],"validation":{"canonical_url":validation.get("canonical_url"),
                    "main_text_chars":validation.get("main_text_chars"),"article_text_chars":validation.get("article_text_chars"),
                    "paragraphs":validation.get("paragraphs"),"pmid":validation.get("pmid"),"error":validation.get("error"),
                    "challenge_marker":validation.get("challenge_marker"),"canonical":validation.get("canonical")}}
            if validation["ok"]:
                source_pmid_ids=metadata.get("pmids",item.get("pmids",[]))
                html_records.append({"pmcid":pmcid,"pmids":source_pmid_ids,"title":validation.get("title") or metadata.get("title"),
                    "license":license_id,"format":"PMC article HTML full text","body_text":validation["body_text"],
                    "body_text_characters":len(validation["body_text"]),"canonical_url":validation["canonical_url"],
                    "html_endpoint":provenance["html_endpoint"],"html_path":provenance["html_path"],"retrieval_source":provenance["retrieval_source"],
                    "source_xml_status":"metadata_only_no_article_body"})
                status["status"]="html_fallback_recovered"
            else:
                status["status"]=validation["status"]
                status["error_details"]={k:v for k,v in validation.items() if k not in {"ok","status"}}
            statuses.append(status)
        except Exception as exc:
            statuses.append({"pmcid":pmcid,"license":license_id,"html_endpoint":url,
                             "retrieval_source":"official_pmc_article_html","status":"html_fallback_fetch_error","error":str(exc)[:500]})
        if index+1<len(failures): time.sleep(.4)
    if html_records:
        core.emit_records(source,"grin_html_full_text",html_records,input_paths=[progress_path,core.PROCESSED/source/"license_metadata.jsonl.gz"],
            description="Separately labeled PMC official article HTML full text for licensed targets whose PMC EFetch XML response contained metadata but no body. HTML was accepted only after canonical PMCID and substantial article-body checks; this does not alter or replace verified JATS.")
    status_by_id={row["pmcid"]:row for row in statuses}
    retry_rows=[]
    for original in core.read_records(core.PROCESSED/source/"fulltext_retry_queue.jsonl.gz"):
        current=status_by_id.get(original.get("pmcid"))
        row=dict(original)
        if current:
            row["html_fallback"]={k:v for k,v in current.items() if k!="validation"}
        retry_rows.append(row)
    if retry_rows:
        core.emit_records(source,"fulltext_retry_queue",retry_rows,input_paths=[progress_path,core.RAW/source],
            description="Original licensed XML retrieval failures preserved with one bounded official PMC HTML fallback outcome per target.")
    audit={"requested_xml_body_missing_ids":len(failures),"attempted_html_ids":len(statuses),
           "recovered_count":len(html_records),"recovered_ids":sorted(row["pmcid"] for row in html_records),
           "unavailable_ids":sorted(row["pmcid"] for row in statuses if row["status"]!="html_fallback_recovered"),
           "per_id":statuses,"limitation":"HTML copies are a separately labeled format. They do not replace the XML dataset and failed/challenge/metadata-only pages remain unavailable."}
    current=core.manifest(source)
    coverage=dict(current.get("coverage",{}))
    jats_ids={row["pmcid"] for row in core.read_records(core.PROCESSED/source/"grin_licensed_full_text.jsonl.gz")}
    html_ids={row["pmcid"] for row in html_records}
    coverage.update({"downloaded_html_records":len(html_ids),"distinct_fulltext_articles_jats_or_html":len(jats_ids|html_ids),
                     "fulltext_fetch_unresolved_after_html":len(audit["unavailable_ids"]),
                     "xml_retry_queue_note":f"Original {len(failures)} XML/body failures remain recorded; nested HTML outcomes identify the {len(html_ids)} recovered in HTML."})
    core.update_manifest(source,html_fallback_audit=audit,coverage=coverage)
    return audit


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("source",choices=["pubmed","grin","clinicaltrials","ctg_diseases","reporter","reporter_grin","preprints","pmc","pmc_grin","pmc_html_retry","all"])
    p.add_argument("--email",default=os.environ.get("HARVEST_CONTACT_EMAIL"),help="Optional contact email sent to NCBI E-utilities; defaults to HARVEST_CONTACT_EMAIL")
    p.add_argument("--pubmed-start-year",type=int,default=1900)
    p.add_argument("--reporter-start-year",type=int,default=1985)
    args=p.parse_args()
    if args.source in ("pubmed","all"): harvest_pubmed(args.email,start_year=args.pubmed_start_year)
    if args.source in ("grin","all"):
        focused=harvest_grin_pubmed(args.email)
        harvest_pmc_linked(focused,source="pmc_grin_oa",dataset_name="grin_licensed_full_text")
    if args.source in ("clinicaltrials","all"): harvest_clinicaltrials()
    if args.source in ("ctg_diseases","all"): harvest_ctg_disease_names()
    if args.source in ("reporter","all"): harvest_reporter(start_year=args.reporter_start_year)
    if args.source=="reporter_grin": harvest_reporter_grin(start_year=args.reporter_start_year)
    if args.source in ("preprints","all"): harvest_preprints()
    if args.source=="pmc": harvest_pmc_linked()
    if args.source=="pmc_grin": harvest_pmc_linked(core.PROCESSED/"grin_literature/grin_gene_citations.jsonl.gz",source="pmc_grin_oa",dataset_name="grin_licensed_full_text")
    if args.source=="pmc_html_retry": retry_pmc_html_fulltext()


if __name__=="__main__":main()
