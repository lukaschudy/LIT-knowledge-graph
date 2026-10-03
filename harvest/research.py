"""Acquisition of literature and study records relevant to rare diseases.

These functions preserve source records and search provenance. They do not
assert that a record proves a biological or clinical relationship.
"""
from __future__ import annotations

import argparse
import calendar
import json
import hashlib
import os
import re
import time
import xml.etree.ElementTree as ET
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
        condition=" OR ".join(f'"{re.sub(r"[()\\[\\]{{}}]", " ", n).replace(chr(34), "")}"' for n in names)
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
    out=core.emit_records(source,"rare_disease_studies",studies.values(),input_paths=[existing_path,path],
        description="Union of generic rare/orphan/neurodevelopmental/inherited condition searches and exhaustively paged RareSource preferred disease-name OR batches. Membership records the complete batch term list; API response does not reveal which OR operand matched each study.")
    core.update_manifest(source,status="complete_with_query_errors" if query_errors else "complete",disease_name_source=str(path.relative_to(core.ROOT)),disease_name_coverage={"preferred_names":sum(len(x) for x in _disease_batches(path)),"batches":batch_count,"batches_detail":batch_stats,"query_errors":query_errors,"unique_studies_after_union":len(studies),"limitation":"A study returned for an OR batch is linked to that batch's full list of candidate names because the API does not identify which operand matched. Source query recall remains spelling and condition-index dependent."})
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
                    path=core.download(source,REPORTER_URL,filename,license_name="NIH RePORTER public project metadata",version="v2",method="POST",json_body=body)
                    payload=_json(path); meta=payload.get("meta",{}); rows=payload.get("results",[])
                    if total is None: total=int(meta.get("total",0))
                    if total>12000:
                        raise RuntimeError(f"RePORTER FY{year} {field}/{term} has {total} matches, above documented offset range; needs a finer source-supported partition")
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
            path=core.download(source,REPORTER_URL,f"grin-fy-{year}-offset-{offset:07d}.json",license_name="NIH RePORTER public project metadata",version="v2",method="POST",json_body=body)
            payload=_json(path); meta=payload.get("meta",{}); rows=payload.get("results",[])
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
    core.update_manifest(source,status="complete_with_query_errors" if errors else "complete",grin_query=search_text,grin_coverage={"aliases":list(aliases),"unique_project_application_fy_subprojects":len(unique),"fiscal_years":fiscal,"query_errors":errors,"limitation":"Text search is source-indexed and alias-based; it does not imply project relevance or experimental validation."})
    return out


def audit_reporter_cache():
    """Offline integrity audit of all cached RePORTER query pages in the manifest."""
    source="nih_reporter"; m=core.manifest(source); groups={}; rawdir=core.RAW/source
    for filename,entry in m.get("artifacts",{}).items():
        body=entry.get("request_body")
        if not isinstance(body,dict) or not filename.endswith(".json"): continue
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
        group["keys"].update((x.get("appl_id"),x.get("subproject_id"),x.get("fiscal_year")) for x in rows)
    audit=[]
    for (year,field,term,operator),g in groups.items():
        row={"fiscal_year":year,"field":field,"term":term,"operator":operator,"reported_total":g["expected"],"records_seen":g["rows"],
             "unique_application_keys":len(g["keys"]),"offsets":sorted(g["offsets"])}
        if "inconsistent_totals" in g: row["inconsistent_totals"]=g["inconsistent_totals"]
        if g["rows"]!=g["expected"] or len(g["keys"])!=g["expected"] or "inconsistent_totals" in g: row["error"]="reported total, row count, or unique-key count mismatch"
        audit.append(row)
    errors=[x for x in audit if x.get("error")]
    core.update_manifest(source,status="complete_with_query_errors" if errors else m.get("status","complete"),broad_cache_audit={"queries":len(audit),"query_errors":errors,"queries_detail":audit,"all_cached_queries_complete":not errors})
    return audit


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
    linked={}; missing=0; excluded_nonfocus=0; scanned_citations=0
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
        if not found: missing+=1
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
            item["status"]="license_unknown_or_incompatible"
            queued.append(item)
    # Keep metadata mapping to original IDs and PMID membership for audit.
    core.emit_records(source,"license_metadata",(
        {"pmcid":pid,"pmids":linked.get(pid,[]),"is_open_access":row.get("isOpenAccess"),"license":row.get("license"),
         "europe_pmc_source":row.get("source"),"pmid":row.get("pmid"),"doi":row.get("doi"),"title":row.get("title"),
         "raw_metadata":row} for pid,row in sorted(metadata.items())),input_paths=[pubmed_path,core.RAW/source],
        description="Europe PMC core metadata queried by exact PMCID groups. isOpenAccess and source license identifiers retained; no license inferred from PMC membership.")
    fulltexts=[]; retrieval_queue=[]
    for pmcid,item in eligible.items():
        url=f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"
        try:
            path=_get(source,url,f"licensed-jats-{pmcid}.xml","Europe PMC full text; compatible explicit CC license verified in core metadata",item["license"])
            article=ET.parse(path).getroot()
            found=article.find(".//article-id[@pub-id-type='pmc']")
            if found is None: found=article.find(".//article-id[@pub-id-type='pmcid']")
            returned_pmcid=(_text(found) or "").upper()
            if returned_pmcid and not returned_pmcid.startswith("PMC"): returned_pmcid="PMC"+returned_pmcid
            if returned_pmcid!=pmcid:
                retrieval_queue.append({**item,"status":"fulltext_pmcid_mismatch","returned_pmcid":returned_pmcid}); continue
            item.update({"body_license":[item["license"]],"supplementary_links":[
                {"href":el.get("{http://www.w3.org/1999/xlink}href"),"label":el.get("{http://www.w3.org/1999/xlink}title"),"article_license":item["license"]}
                for el in article.findall(".//supplementary-material") if el.get("{http://www.w3.org/1999/xlink}href")],
                "jats_xml":ET.tostring(article,encoding="unicode")})
            fulltexts.append(item)
        except Exception as exc:
            retrieval_queue.append({**item,"status":"fulltext_fetch_error","error":str(exc)[:500]})
        time.sleep(.2)
    if fulltexts:
        core.emit_records(source,dataset_name,fulltexts,input_paths=[pubmed_path,core.RAW/source],
            description="Europe PMC JATS fetched only after core metadata exposed an explicit compatible Creative Commons license identifier.")
    if queued:
        core.emit_records(source,"rights_review_queue",queued,input_paths=[pubmed_path,core.RAW/source],
            description="Linked PMC identifiers lacking an explicit compatible license identifier in Europe PMC core metadata. No full text fetched for these records.")
    if retrieval_queue:
        core.emit_records(source,"fulltext_retry_queue",retrieval_queue,input_paths=[pubmed_path,core.RAW/source],description="Europe PMC full-text fetch or identity errors for records with an explicit compatible license.")
    has_errors=bool(metadata_errors or retrieval_queue or any(x["missing_pmcids"] or x["unexpected_pmcids"] or x["reported_hits"]!=x["returned_unique_pmcids"] for x in exact_batches))
    coverage={"pubmed_citations_scanned":scanned_citations,"focus_citations_excluded":excluded_nonfocus,"linked_articles_with_pmcid":len(linked),
        "metadata_pmcids_expected":len(linked),"metadata_pmcids_returned":len(metadata),"metadata_exact_id_set_match":set(linked)==set(metadata),
        "metadata_batches":exact_batches,"metadata_errors":metadata_errors,"compatible_license_candidates":len(eligible),
        "downloaded_jats_records":len(fulltexts),"queued_for_rights_review":len(queued),"queued_for_fetch_retry":len(retrieval_queue),
        "citations_without_pmcid":missing,"license_unknown_or_incompatible":sum(x["status"]=="license_unknown_or_incompatible" for x in queued),
        "limitation":"The corpus is limited to PubMed-linked PMCIDs in the declared focus query. Exact Europe PMC PMCID search results retain source isOpenAccess and license fields. Full text is fetched only for source-provided CC BY/SA/NC or CC0 identifiers; missing, non-CC, ND, and unknown licenses stay queued. Supplement links are recorded; assets are not fetched unless separately rights-verified."}
    if source=="pmc_grin_oa": coverage["focused_scope"]={"pmids":sorted(GRIN_FULLTEXT_PMIDS),"pmcids":sorted(GRIN_FULLTEXT_PMCIDS),"title_abstract_mesh_regex":GRIN_FULLTEXT_RE.pattern}
    core.update_manifest(source,status="complete_with_fetch_errors" if has_errors else ("complete_with_rights_queue" if queued else "complete"),coverage=coverage)
    return len(fulltexts),len(queued)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("source",choices=["pubmed","grin","clinicaltrials","ctg_diseases","reporter","reporter_grin","preprints","pmc","pmc_grin","all"])
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


if __name__=="__main__":main()
