"""Stateless, source-specific conversion of harvested rows to typed graph facts.

This graph is an index of explicit source relationships, not a review system.
Unknown row shapes intentionally return no graph edges; the caller retains the
original row as a provenance record independently.
"""
from __future__ import annotations

import re
import hashlib
from typing import Any


_VALID_CURIE = re.compile(r"^(?:[A-Za-z][A-Za-z0-9_-]*:[A-Za-z0-9][A-Za-z0-9._/()%-]*|ENS(?:MUS)?G\d+)$")
_ORCID = re.compile(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
_DOI = re.compile(r"^10\.\d{4,9}/\S+$", re.I)
_MAX_LABEL = 300


class _Output:
    def __init__(self):
        self.nodes: dict[str, dict[str, Any]] = {}
        self.edges: set[tuple[str, str, str]] = set()

    def node(self, identifier: str | None, kind: str, label: Any, aliases=()):
        if not isinstance(identifier, str) or not _VALID_CURIE.fullmatch(identifier):
            return None
        text = _label(label)
        if not text:
            text = identifier
        row = self.nodes.get(identifier)
        if row is None:
            row = {"id": identifier, "type": kind, "label": text[:_MAX_LABEL]}
            self.nodes[identifier] = row
        known = set(row.get("aliases", []))
        for alias in aliases if isinstance(aliases, (list, tuple, set)) else ():
            value = _label(alias)
            if value and value != row["label"] and value not in known and len(known) < 20:
                known.add(value[:_MAX_LABEL])
        if known:
            row["aliases"] = sorted(known)
        return identifier

    def edge(self, subject: str | None, predicate: str, obj: str | None):
        if subject and obj and subject != obj and isinstance(predicate, str) and predicate:
            self.edges.add((subject, predicate, obj))


def _label(value: Any) -> str:
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    return ""


def _value(row: dict, *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, "", "-", "NA", "N/A"):
            return value
    return None


def _curie(value: Any, default_prefix: str | None = None) -> str | None:
    text = _label(value)
    if not text:
        return None
    text = text.strip()
    if text.startswith("http://purl.obolibrary.org/obo/"):
        text = text.rsplit("/", 1)[-1].replace("_", ":", 1)
    if text.startswith("https://ror.org/"):
        text = "ROR:" + text.rsplit("/", 1)[-1]
    if text.startswith("MONDO_"):
        text = "MONDO:" + text[6:]
    if text.startswith("MONDO:MONDO:"):
        text = "MONDO:" + text[len("MONDO:MONDO:"):]
    if re.fullmatch(r"R-[A-Z]{3}-\d+", text):
        text = "Reactome:" + text
    if re.fullmatch(r"ENSG\d+", text) or re.fullmatch(r"ENSMUSG\d+", text):
        return text
    if ":" not in text and default_prefix:
        text = default_prefix + ":" + text
    return text if _VALID_CURIE.fullmatch(text) else None


def _gene_id(row: dict) -> str | None:
    # HGNC is preferred; direct ENSEMBL/NCBI identifiers remain separately
    # represented unless an HGNC registry row explicitly linked them.
    return (_curie(_value(row, "hgnc_id", "HGNC_ID", "HGNC ID", "GENE ID (HGNC)", "HGNC/ISCA"), "HGNC")
            or _curie(_value(row, "ensembl_gene_id", "Ensembl Gene ID", "targetFromSourceId", "db_object_id"), "ENSG")
            or _curie(_value(row, "gene_curie"))
            or _curie(_value(row, "gene_id", "GeneID", "ncbi_gene_id", "human_entrez_id", "entrez_id"), "NCBIGene"))


def _disease_id(value: Any) -> str | None:
    text = _curie(value)
    if text and text.startswith("OMIMPS:"):
        return "OMIM:" + text.split(":", 1)[1]
    if text and text.startswith("ORPHA:"):
        return "Orphanet:" + text.split(":", 1)[1]
    return text


def _add_entity(out: _Output, curie: Any, label: Any, kind: str, aliases=()) -> str | None:
    return out.node(_curie(curie), kind, label, aliases)


def _split_values(value: Any, separators=r"[|,;\s]+") -> list[str]:
    if not isinstance(value, str):
        return []
    return [x for x in re.split(separators, value.strip()) if x and x not in {"-", "NA"}]


def _disease_tokens(text: Any) -> list[tuple[str, str]]:
    """Extract only explicitly typed disease identifiers from a source field."""
    if not isinstance(text, str):
        return []
    found = []
    for raw in re.split(r"[|,;]+", text):
        token = raw.strip()
        # ClinVar's PhenotypeIDS format prefixes MONDO with MONDO: twice.
        if token.startswith("MONDO:MONDO:"):
            token = token[len("MONDO:"):]
        m = re.match(r"^(MONDO|OMIM|Orphanet|ORPHA|DOID|GARD|MedGen|UMLS|MeSH|ICD10CM):(.+)$", token, re.I)
        if not m:
            continue
        prefix, local = m.group(1), m.group(2)
        prefix = {"orpha": "Orphanet", "medgen": "MedGen", "mesh": "MeSH"}.get(prefix.casefold(), prefix.upper() if prefix.upper() in {"MONDO", "OMIM", "DOID", "GARD", "UMLS", "ICD10CM"} else prefix)
        curie = _disease_id(f"{prefix}:{local}")
        if curie and curie not in {item[0] for item in found}:
            found.append((curie, curie))
    return found


def _publication_id(row: dict) -> tuple[str | None, str]:
    pmid = _value(row, "pmid", "PMID", "pubmed_id")
    if pmid:
        value = _curie(pmid, "PMID")
        if value:
            return value, _label(_value(row, "title"))
    pmcid = _value(row, "pmcid", "PMCID")
    if pmcid:
        return _curie(pmcid, "PMCID"), _label(_value(row, "title"))
    doi = _value(row, "doi", "DOI")
    if doi:
        normalized = _label(doi).removeprefix("https://doi.org/").removeprefix("http://doi.org/")
        if _DOI.fullmatch(normalized):
            return "DOI:" + normalized.lower(), _label(_value(row, "title"))
    epmc_id = _value(row, "id")
    if epmc_id:
        source = _label(_value(row, "source")).upper()
        if source == "MED":
            return _curie(epmc_id, "PMID"), _label(_value(row, "title"))
        return _curie(f"EPMC:{source or 'UNKNOWN'}-{epmc_id}"), _label(_value(row, "title"))
    return None, ""


def _author_edges(out: _Output, row: dict, publication: str):
    author_list = row.get("authorList")
    authors = author_list.get("author", []) if isinstance(author_list, dict) else []
    if not isinstance(authors, list):
        return
    for author in authors:
        if not isinstance(author, dict):
            continue
        ids = author.get("authorId")
        if isinstance(ids, dict):
            ids = [ids]
        if not isinstance(ids, list):
            continue
        for identifier in ids:
            if not isinstance(identifier, dict) or str(identifier.get("type", "")).upper() != "ORCID":
                continue
            value = str(identifier.get("value", "")).removeprefix("https://orcid.org/")
            if _ORCID.fullmatch(value):
                person = out.node("ORCID:" + value, "Person", _value(author, "fullName") or value)
                out.edge(person, "AUTHORED", publication)
                break


def _obo_tag(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x) for x in value if x not in (None, "")]
    return [str(value)] if value not in (None, "") else []


def _obo_term(out: _Output, tags: dict, kind: str):
    ids = _obo_tag(tags.get("id"))
    names = _obo_tag(tags.get("name"))
    if not ids:
        return
    identifier = _curie(ids[0])
    if not identifier:
        return
    node = out.node(identifier, kind, names[0] if names else identifier,
                    [*(_obo_tag(tags.get("synonym")))])
    for parent_line in _obo_tag(tags.get("is_a")):
        parent = _curie(parent_line.split(" !", 1)[0].strip())
        if parent:
            out.node(parent, kind, parent)
            out.edge(node, "IS_A", parent)


def _xml_children(value: Any):
    return value.get("children", []) if isinstance(value, dict) and isinstance(value.get("children"), list) else []


def _xml_find(value: Any, tag: str) -> list[dict]:
    found = []
    def walk(node):
        if not isinstance(node, dict):
            return
        if node.get("tag") == tag:
            found.append(node)
        for child in _xml_children(node):
            walk(child)
    walk(value)
    return found


def _xml_text(node: Any) -> str:
    return _label(node.get("text")) if isinstance(node, dict) else ""


def _orpha_disease(out: _Output, row: dict) -> str | None:
    code = next((_xml_text(n) for n in _xml_find(row, "OrphaCode") if _xml_text(n)), None)
    name = next((_xml_text(n) for n in _xml_find(row, "Name") if _xml_text(n)), "")
    if code:
        return out.node("Orphanet:" + code, "Disease", name or ("Orphanet " + code))
    return None


def _adapt_orphadata(out: _Output, dataset: str, row: dict):
    if dataset == "classifications" and row.get("tag") != "Disorder":
        for disorder in _xml_find(row, "Disorder"):
            _adapt_orphadata(out, "epidemiology", disorder)
        return
    if row.get("tag") != "Disorder":
        return
    disease = _orpha_disease(out, row)
    if not disease:
        return
    if dataset == "phenotypes":
        for association in _xml_find(row, "HPODisorderAssociation"):
            hpo = next((_xml_text(n) for n in _xml_find(association, "HPOId") if _xml_text(n)), None)
            label = next((_xml_text(n) for n in _xml_find(association, "HPOTerm") if _xml_text(n)), hpo)
            phenotype = out.node(_curie(hpo), "Phenotype", label)
            out.edge(disease, "HAS_PHENOTYPE", phenotype)
    elif dataset == "genes":
        for association in _xml_find(row, "DisorderGeneAssociation"):
            gene_node = next(iter(_xml_find(association, "Gene")), None)
            if not gene_node:
                continue
            symbol = next((_xml_text(n) for n in _xml_find(gene_node, "Symbol") if _xml_text(n)), "")
            gene_id = None
            for ref in _xml_find(gene_node, "ExternalReference"):
                source = next((_xml_text(n) for n in _xml_find(ref, "Source") if _xml_text(n)), "")
                value = next((_xml_text(n) for n in _xml_find(ref, "Reference") if _xml_text(n)), "")
                if source.casefold() == "hgnc" and value:
                    gene_id = _curie(value, "HGNC"); break
                if source.casefold() in {"ensembl", "ensembl genes"} and value.startswith("ENSG"):
                    gene_id = _curie(value); break
            if gene_id is None and gene_node.get("attributes", {}).get("id"):
                gene_id = _curie("OrphaGene:" + gene_node["attributes"]["id"])
            gene = out.node(gene_id, "Gene", symbol or gene_id)
            out.edge(disease, "ASSOCIATED_WITH_GENE", gene)
    elif dataset == "cross_references":
        for ref in _xml_find(row, "ExternalReference"):
            source = next((_xml_text(n) for n in _xml_find(ref, "Source") if _xml_text(n)), "")
            value = next((_xml_text(n) for n in _xml_find(ref, "Reference") if _xml_text(n)), "")
            relation = next((_xml_text(n) for n in _xml_find(ref, "Name") if _xml_text(n)), "")
            prefix = {"mondo": "MONDO", "omim": "OMIM", "orphanet": "Orphanet", "ordo": "Orphanet"}.get(source.casefold())
            if not prefix or not value:
                continue
            target_id = _curie(value, prefix)
            target = out.node(target_id, "Disease", target_id)
            predicate = "SAME_AS" if "exact mapping" in relation.casefold() else "MAPPED_TO"
            out.edge(disease, predicate, target)


def adapt(source: str, dataset: str, row: dict) -> tuple[list[dict], list[tuple[str, str, str]]]:
    """Adapt one harvested source/dataset row into nodes and explicit edges.

    The function is pure with respect to process state and bounds every label.
    Unknown datasets and malformed/incomplete records return empty lists.
    """
    if not isinstance(source, str) or not isinstance(dataset, str) or not isinstance(row, dict):
        return [], []
    out = _Output()
    try:
        _adapt(out, source, dataset, row)
    except (KeyError, TypeError, ValueError, AttributeError):
        # A malformed row remains available in the caller's provenance store.
        # No partial, guessed relationship escapes this adapter.
        return [], []
    return list(out.nodes.values()), sorted(out.edges)


def _adapt(out: _Output, source: str, dataset: str, row: dict):
    if source == "grin_reference" and isinstance(row.get("native"), dict):
        upstream = row.get("upstream_source")
        upstream_dataset = row.get("upstream_dataset")
        if not upstream:
            wrapped_dataset = _value(row, "_dataset")
            source_guess = {"hpo_disease_phenotypes": "hpo"}.get(wrapped_dataset)
            upstream = source_guess
            upstream_dataset = {"hpo_disease_phenotypes": "disease_phenotype_annotations"}.get(wrapped_dataset)
        return _adapt(out, upstream or "", upstream_dataset or "", row["native"])

    if source in {"hgnc", "grin_reference"} and dataset == "hgnc_complete_set":
        _hgnc(out, row); return
    if source == "hgnc" and dataset == "withdrawn":
        node = out.node(_curie(_value(row, "HGNC_ID")), "Gene", _value(row, "WITHDRAWN_SYMBOL"))
        merged = _value(row, "MERGED_INTO_REPORT(S) (i.e HGNC_ID|SYMBOL|STATUS)")
        target = _curie(str(merged).split("|", 1)[0]) if merged else None
        if target:
            out.node(target, "Gene", target); out.edge(node, "MERGED_INTO", target)
        return
    if source in {"mondo", "hpo", "go"} and dataset in {"obo_stanzas", "ontology_terms"}:
        if row.get("stanza_type", "").casefold() in {"term", "[term]"}:
            _obo_term(out, row.get("tags", {}), "Disease" if source == "mondo" else "Phenotype" if source == "hpo" else "OntologyTerm")
        return
    if source == "go" and dataset == "ontology":
        ids = _obo_tag(row.get("id")); names = _obo_tag(row.get("name"))
        if ids:
            term = out.node(_curie(ids[0]), "OntologyTerm", names[0] if names else ids[0])
            for parent in _obo_tag(row.get("is_a")):
                parent_id = _curie(parent.split(" !", 1)[0])
                p = out.node(parent_id, "OntologyTerm", parent_id)
                out.edge(term, "IS_A", p)
        return
    if source == "orphadata":
        record = row.get("record") if dataset == "classifications" else row
        if isinstance(record, dict):
            _adapt_orphadata(out, dataset, record)
        return
    if source == "mondo" and dataset == "owl_axioms":
        _owl_term(out, row); return
    if source == "hgnc" or (source == "grin_reference" and row.get("_dataset") == "hgnc_complete_set"):
        if dataset == "hgnc_complete_set": _hgnc(out, row)
        return
    if source == "clingen" and dataset in {"gene_disease_validity", "gene_disease_validity_lumping_splitting"}:
        gene = out.node(_gene_id(row), "Gene", _value(row, "GENE SYMBOL"))
        disease = out.node(_disease_id(_value(row, "DISEASE ID (MONDO)")), "Disease", _value(row, "DISEASE LABEL"))
        report = _value(row, "ONLINE REPORT")
        if isinstance(report, str) and report:
            report_token = report.rsplit("/", 1)[-1]
        else:
            identity = "|".join(_label(_value(row, key)) for key in
                                ("GENE ID (HGNC)", "DISEASE ID (MONDO)", "MOI", "CLASSIFICATION"))
            report_token = "row-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]
        assertion_id = "ClinGenAssertion:" + report_token.replace(":", "-")
        assertion = out.node(_curie(assertion_id), "Assertion", _value(row, "CLASSIFICATION") or assertion_id)
        out.edge(gene, "HAS_CLINGEN_ASSERTION", assertion)
        out.edge(assertion, "ASSERTS_RELATION_TO_DISEASE", disease)
        classification = _label(_value(row, "CLASSIFICATION"))
        if classification:
            class_node = out.node(_curie("ClinGenClassification:" + re.sub(r"[^A-Za-z0-9_-]+", "-", classification)),
                                  "AssertionClassification", classification)
            out.edge(assertion, "HAS_CLASSIFICATION", class_node)
        mode = _inheritance_curie(_value(row, "MOI"))
        if mode:
            out.node(mode, "OntologyTerm", _value(row, "MOI")); out.edge(assertion, "HAS_REPORTED_INHERITANCE", mode)
        return
    if source == "clingen" and dataset in {"gene_dosage", "gene_dosage_all"}:
        gene_label = _value(row, "GENE SYMBOL", "GENE/REGION")
        gene = out.node(_gene_id(row), "Gene", gene_label)
        for field, predicate in (("HAPLOINSUFFICIENCY", "HAS_HAPLOINSUFFICIENCY_ASSERTION"),
                                 ("TRIPLOSENSITIVITY", "HAS_TRIPLOSENSITIVITY_ASSERTION")):
            classification = _label(_value(row, field))
            if not classification:
                continue
            assertion_key = (_label(_value(row, "HGNC ID", "HGNC/ISCA", "_record")).replace(":", "-")
                             + "-" + field.casefold())
            assertion = out.node(_curie("ClinGenDosageAssertion:" + assertion_key),
                                 "Assertion", classification)
            class_id = _curie("ClinGenDosageClassification:" + re.sub(r"[^A-Za-z0-9_-]+", "-", classification))
            class_node = out.node(class_id, "AssertionClassification", classification)
            out.edge(gene, predicate, assertion)
            out.edge(assertion, "HAS_CLASSIFICATION", class_node)
        # Dosage evidence is not a pathogenic variant or functional assay result.
        return
    if source == "gencc" and dataset == "assertions":
        gene = out.node(_curie(_value(row, "gene_curie", "submitted_as_hgnc_id")), "Gene", _value(row, "gene_symbol"))
        disease = out.node(_disease_id(_value(row, "disease_curie")), "Disease", _value(row, "disease_title"))
        assertion = out.node(_curie(_value(row, "sgc_id"), "GenCC"), "Assertion", _value(row, "classification_title", "sgc_id"))
        out.edge(gene, "HAS_GENCC_ASSERTION", assertion)
        out.edge(assertion, "ASSERTS_RELATION_TO_DISEASE", disease)
        classification_id = _curie(_value(row, "classification_curie"))
        if classification_id:
            classification = out.node(classification_id, "AssertionClassification", _value(row, "classification_title"))
            out.edge(assertion, "HAS_CLASSIFICATION", classification)
        submitter = _curie(_value(row, "submitter_curie"))
        if submitter:
            org = out.node(submitter, "Organization", _value(row, "submitter_title"))
            out.edge(org, "SUBMITTED_ASSERTION", assertion)
        moi = _inheritance_curie(_value(row, "moi_curie"))
        if moi:
            out.node(moi, "OntologyTerm", _value(row, "moi_title")); out.edge(assertion, "HAS_REPORTED_INHERITANCE", moi)
        return
    if source == "clinvar" and dataset == "variant_summary":
        _clinvar_variant(out, row); return
    if source == "clinvar" and dataset == "gene_condition_source_id":
        gene = out.node(_curie(_value(row, "GeneID"), "NCBIGene"), "Gene", _value(row, "AssociatedGenes"))
        disease = out.node(_disease_id(_value(row, "SourceID")), "Disease", _value(row, "DiseaseName"))
        out.edge(gene, "HAS_CLINVAR_CONDITION", disease)
        return
    if source == "hpo" and dataset in {"disease_phenotype_annotations", "hpo_disease_phenotypes"}:
        disease = out.node(_disease_id(_value(row, "database_id")), "Disease", _value(row, "disease_name"))
        phenotype = out.node(_curie(_value(row, "hpo_id")), "Phenotype", _value(row, "hpo_id"))
        qualifier = _label(_value(row, "qualifier")).upper()
        out.edge(disease, "NOT_HAS_PHENOTYPE" if qualifier == "NOT" else "HAS_PHENOTYPE", phenotype)
        return
    if source == "hpo" and dataset == "genes_to_phenotype":
        gene = out.node(_curie(_value(row, "ncbi_gene_id"), "NCBIGene"), "Gene", _value(row, "gene_symbol"))
        phenotype = out.node(_curie(_value(row, "hpo_id")), "Phenotype", _value(row, "hpo_name"))
        out.edge(gene, "HAS_PHENOTYPE", phenotype)
        disease_id = _disease_id(_value(row, "disease_id"))
        if disease_id:
            disease = out.node(disease_id, "Disease", disease_id); out.edge(disease, "HAS_PHENOTYPE", phenotype)
        return
    if source == "hpo" and dataset == "genes_to_disease":
        gene = out.node(_curie(_value(row, "ncbi_gene_id"), "NCBIGene"), "Gene", _value(row, "gene_symbol"))
        disease = out.node(_disease_id(_value(row, "disease_id")), "Disease", _value(row, "disease_id"))
        out.edge(gene, "ASSOCIATED_WITH_DISEASE", disease)
        return
    if source == "mgi" and dataset == "hmd_humanphenotype":
        human = out.node(_curie(_value(row, "human_entrez_id"), "NCBIGene"), "Gene", _value(row, "human_symbol"))
        mouse = out.node(_curie(_value(row, "mouse_mgi_id")), "Gene", _value(row, "mouse_symbol"))
        out.edge(human, "HOMOLOGOUS_TO", mouse)
        for phenotype_id in _split_values(_value(row, "phenotype_ids")):
            phenotype = out.node(_curie(phenotype_id), "Phenotype", phenotype_id)
            out.edge(mouse, "HAS_MODEL_PHENOTYPE", phenotype)
        return
    if source == "go" and dataset == "human_annotations":
        _go_annotation(out, row); return
    if source == "reactome" and dataset == "UniProt2Reactome_All_Levels":
        protein = out.node(_curie(_value(row, "uniprot_accession"), "UniProt"), "Protein", _value(row, "uniprot_accession"))
        pathway = out.node(_curie(_value(row, "reactome_pathway_id")), "Pathway", _value(row, "pathway_name"))
        out.edge(protein, "PARTICIPATES_IN_PATHWAY", pathway)
        species_name = _label(_value(row, "species"))
        taxon = {"homo sapiens": "NCBITaxon:9606", "mus musculus": "NCBITaxon:10090",
                 "drosophila melanogaster": "NCBITaxon:7227", "rattus norvegicus": "NCBITaxon:10116"}.get(species_name.casefold())
        pathway_token = _label(_value(row, "reactome_pathway_id"))
        code_match = re.match(r"^R-([A-Z]{3})-", pathway_token)
        species_id = taxon or ("ReactomeSpecies:" + code_match.group(1) if code_match else None)
        species = out.node(species_id, "Species", species_name)
        out.edge(pathway, "PATHWAY_IN_SPECIES", species)
        return
    if source == "reactome" and dataset == "ReactomePathways":
        pathway = out.node(_curie(_value(row, "reactome_pathway_id")), "Pathway", _value(row, "pathway_name"))
        return
    if source == "reactome" and dataset == "ReactomePathwaysRelation":
        parent = out.node(_curie(_value(row, "parent_pathway_id")), "Pathway", _value(row, "parent_pathway_id"))
        child = out.node(_curie(_value(row, "child_pathway_id")), "Pathway", _value(row, "child_pathway_id"))
        out.edge(parent, "CONTAINS_PATHWAY", child)
        return
    if source == "open_targets" and dataset in {"target_associations", "grin_gene_disease_evidence"}:
        if dataset == "target_associations":
            _open_target_association(out, row)
        else:
            _open_target_evidence(out, row)
        return
    if source == "open_targets" and dataset == "rare_diseases":
        disease = out.node(_disease_id(_value(row, "id")), "Disease", _value(row, "name"))
        targets = row.get("associatedTargets", {}).get("rows", []) if isinstance(row.get("associatedTargets"), dict) else []
        for item in targets if isinstance(targets, list) else []:
            target = item.get("target", {}) if isinstance(item, dict) else {}
            gene = out.node(_curie(_value(target, "id")), "Gene", _value(target, "approvedSymbol"))
            out.edge(gene, "ASSOCIATED_WITH_DISEASE", disease)
        return
    if source == "open_targets" and dataset == "drug_candidates":
        disease = out.node(_disease_id(_value(row, "disease_id")), "Disease", _value(row, "disease_name"))
        candidate = row.get("clinical_candidate")
        drug = candidate.get("drug") if isinstance(candidate, dict) else None
        if isinstance(drug, dict):
            drug_node = out.node(_curie(_value(drug, "id"), "ChEMBL"), "Drug", _value(drug, "name"))
            out.edge(drug_node, "CANDIDATE_FOR_DISEASE", disease)
        return
    if source == "clinicaltrials_gov" or (source == "grin_resources" and dataset == "study_records"):
        _clinical_trial(out, row); return
    if source == "europe_pmc_diseases" and dataset == "queries":
        query = out.node(_curie(_value(row, "query_id"), "EPMCQuery"), "SearchQuery", _value(row, "query"))
        return
    if source == "europe_pmc_diseases" and dataset == "search_vocabulary":
        term = _label(_value(row, "term"))
        if term:
            query_id = "EPMCQuery:" + hashlib.sha256(term.casefold().encode("utf-8")).hexdigest()[:20]
            query = out.node(query_id, "SearchQuery", term)
            for disease_id in row.get("disease_source_ids", []) if isinstance(row.get("disease_source_ids"), list) else []:
                disease_id = _disease_id(disease_id)
                disease = out.node(disease_id, "Disease", disease_id)
                out.edge(query, "SEARCHES_FOR_DISEASE", disease)
        return
    if source == "europe_pmc_diseases" and dataset == "query_membership":
        article = _epmc_publication(out, _value(row, "article_id"))
        query = out.node(_curie(_value(row, "query_id"), "EPMCQuery"), "SearchQuery", _value(row, "query_id"))
        out.edge(article, "RETURNED_BY_QUERY", query)
        return
    if source in {"europe_pmc_diseases", "europe_pmc_preprints", "pubmed", "grin_literature", "crossref_grin"}:
        _publication(out, source, dataset, row); return
    if source == "ror" and dataset == "organizations":
        _ror(out, row); return
    if source == "nih_reporter" and dataset in {"rare_disease_projects", "grin_projects"}:
        _nih_project(out, row); return
    if source == "grants_gov" and dataset == "opportunities":
        grant = out.node(_curie(_value(row, "id"), "GrantsGov"), "Grant", _value(row, "title"))
        for membership in row.get("query_membership", []) if isinstance(row.get("query_membership"), list) else []:
            if isinstance(membership, dict) and membership.get("term"):
                qid = "GrantsGovQuery:" + str(membership["term"]).casefold().replace(" ", "-")
                query = out.node(_curie(qid), "SearchQuery", membership["term"])
                out.edge(grant, "RETURNED_BY_QUERY", query)
        return
    if source == "grin_resources" and dataset == "resources":
        resource = out.node(_curie(_value(row, "id"), "AtlasResource"), "Resource", _value(row, "name"))
        return
    if source == "grin_resources" and dataset == "announcements":
        # Individual investigator/institution names are retained as row metadata,
        # not merged into person/organization identities without stable IDs.
        out.node(_curie(_value(row, "id"), "AtlasAnnouncement"), "Announcement", _value(row, "id"))
        return
    if source == "raresource" and dataset == "diseases":
        _raresource_disease(out, row); return
    if source == "raresource" and dataset == "genes":
        gene = out.node(_curie(_value(row, "HGNC ID"), "HGNC") or _curie(_value(row, "Ensembl Gene ID")),
                        "Gene", _value(row, "Gene Information"))
        return
    if source == "mgi":
        _mgi(out, dataset, row); return
    if source == "uniprot" and dataset == "reviewed_human":
        _uniprot(out, row); return
    if source == "grin_clinvar" and dataset == "variant_archives":
        out.node(_curie(_value(row, "variation_id"), "ClinVar"), "Variant", _value(row, "accession"))
        return
    if source == "europe_pmc_recheck":
        if dataset.startswith("identifiers_"):
            article = _epmc_publication(out, _value(row, "article_id"))
            query = out.node(_curie(_value(row, "query_id"), "EPMCQuery"), "SearchQuery", _value(row, "query_id"))
            out.edge(article, "RETURNED_BY_QUERY", query)
            return
        if dataset.startswith("recovered_articles") and isinstance(row.get("native"), dict):
            native = row["native"]
            identifier, title = _publication_id(native)
            publication = out.node(identifier, "Publication", title)
            _author_edges(out, native, publication)
            return
    if source == "grin_primary_tables" and dataset == "table_rows":
        pmcid = _curie(_value(row, "pmcid"), "PMCID")
        source_id = _label(_value(row, "source_id"))
        publication = out.node(pmcid or _curie("AtlasSource:" + source_id), "Publication", source_id or pmcid)
        return
    if source == "grin_supplements" and dataset == "myers2023_supplement_pages":
        pmcid = out.node(_curie(_value(row, "pmcid"), "PMCID"), "Publication", _value(row, "pmcid"))
        return
    if source == "pmc_grin_oa":
        _publication(out, source, dataset, row); return


def _hgnc(out: _Output, row: dict):
    hgnc = out.node(_curie(_value(row, "hgnc_id"), "HGNC"), "Gene", _value(row, "symbol"),
                    [*_split_values(_value(row, "alias_symbol")), *_split_values(_value(row, "prev_symbol"))])
    # HGNC's own cross-reference fields explicitly identify the same registry entry.
    equivalents = [("ensembl_gene_id", "ENSG"), ("entrez_id", "NCBIGene")]
    for key, prefix in equivalents:
        value = _value(row, key)
        target = out.node(_curie(value, prefix), "Gene", _value(row, "symbol"))
        out.edge(hgnc, "SAME_AS", target)
    for value in _split_values(_value(row, "uniprot_ids")):
        protein = out.node(_curie(value, "UniProt"), "Protein", value)
        out.edge(hgnc, "ENCODES", protein)
    omim = _value(row, "omim_id")
    if omim:
        target = out.node(_curie(omim, "OMIM"), "Gene", _value(row, "symbol"))
        out.edge(hgnc, "SAME_AS", target)


def _inheritance_curie(value):
    value = _label(value).casefold()
    return {"ad": "HP:0000006", "autosomal dominant": "HP:0000006",
            "ar": "HP:0000007", "autosomal recessive": "HP:0000007",
            "x-linked": "HP:0001417", "xl": "HP:0001417",
            "mitochondrial": "HP:0001427"}.get(value)


def _clinvar_variant(out: _Output, row: dict):
    variation_id = _value(row, "VariationID")
    if not variation_id:
        return
    variant = out.node(_curie(variation_id, "ClinVar"), "Variant", _value(row, "Name"))
    hgnc_values = _split_values(_value(row, "HGNC_ID"), separators=r"[|;,\s]+")
    gene_symbols = _split_values(_value(row, "GeneSymbol"), separators=r"[|;,\s]+")
    gene_ids = [_curie(value, "HGNC") for value in hgnc_values]
    gene_ids = [value for value in gene_ids if value]
    if not gene_ids:
        gene_id = _gene_id(row)
        if gene_id:
            gene_ids = [gene_id]
    for index, gene_id in enumerate(dict.fromkeys(gene_ids)):
        # Only pair a label when source lists align one-to-one; otherwise use ID.
        label = gene_symbols[index] if len(gene_symbols) == len(gene_ids) and index < len(gene_symbols) else gene_id
        gene = out.node(gene_id, "Gene", label)
        out.edge(variant, "IN_GENE", gene)
    disease_ids = _disease_tokens(_value(row, "PhenotypeIDS"))
    for disease_id, _ in disease_ids:
        disease = out.node(disease_id, "Disease", disease_id)
        out.edge(variant, "HAS_CLINVAR_CONDITION", disease)


def _go_annotation(out: _Output, row: dict):
    db = _label(_value(row, "db"))
    object_id = _label(_value(row, "db_object_id"))
    if not object_id:
        return
    if db == "UniProtKB":
        subject = out.node(_curie(object_id, "UniProt"), "Protein", _value(row, "db_object_symbol"))
    elif db in {"NCBI_Gene", "GeneID", "NCBIGene"}:
        subject = out.node(_curie(object_id, "NCBIGene"), "Gene", _value(row, "db_object_symbol"))
    else:
        subject = out.node(_curie(db + ":" + object_id), "Gene", _value(row, "db_object_symbol"))
    term_id = _curie(_value(row, "go_id"))
    term = out.node(term_id, "OntologyTerm", term_id)
    qualifier = _label(_value(row, "qualifier"))
    if "NOT" in {part.strip().upper() for part in qualifier.split("|")}:
        predicate = "NOT_ANNOTATED_WITH_GO"
    else:
        predicate = {"F": "HAS_MOLECULAR_FUNCTION", "P": "PARTICIPATES_IN_BIOLOGICAL_PROCESS",
                     "C": "LOCATED_IN_CELLULAR_COMPONENT"}.get(_label(_value(row, "aspect")).upper(), "ANNOTATED_WITH_GO")
    out.edge(subject, predicate, term)


def _owl_term(out: _Output, row: dict):
    attributes = row.get("attributes", {})
    about = attributes.get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about") if isinstance(attributes, dict) else None
    identifier = None
    if isinstance(about, str) and "/MONDO_" in about:
        identifier = _curie(about.rsplit("/", 1)[-1].replace("_", ":", 1))
    if not identifier:
        return
    children = _xml_children(row)
    label = next((_xml_text(child) for child in children if child.get("tag", "").endswith("label")), identifier)
    disease = out.node(identifier, "Disease", label)
    for child in children:
        if child.get("tag", "").endswith("subClassOf"):
            resource = child.get("attributes", {}).get("{http://www.w3.org/1999/02/22-rdf-syntax-ns#}resource")
            if resource and "/MONDO_" in resource:
                parent_id = _curie(resource.rsplit("/", 1)[-1].replace("_", ":", 1))
                parent = out.node(parent_id, "Disease", parent_id)
                out.edge(disease, "IS_A", parent)


def _open_target_association(out: _Output, row: dict):
    disease = out.node(_disease_id(_value(row, "disease_id")), "Disease", _value(row, "disease_name"))
    assoc = row.get("target_association")
    target = assoc.get("target", {}) if isinstance(assoc, dict) else {}
    target_id = _curie(_value(target, "id", "targetFromSourceId")) if isinstance(target, dict) else None
    if not target_id and isinstance(row.get("targetFromSourceId"), str):
        target_id = _curie(row["targetFromSourceId"])
    gene = out.node(target_id, "Gene", _value(target, "approvedSymbol", "symbol") if isinstance(target, dict) else target_id)
    out.edge(gene, "ASSOCIATED_WITH_DISEASE", disease)


def _open_target_evidence(out: _Output, row: dict):
    """Keep evidence records and their mapped entities explicit, without turning score into causality."""
    evidence_id = _curie(_value(row, "id"), "OpenTargetsEvidence")
    evidence = out.node(evidence_id, "EvidenceRecord", _value(row, "datasourceId", "id"))
    target_raw = _value(row, "targetFromSourceId")
    target = None
    if target_raw:
        # Open Targets target evidence commonly uses an Ensembl gene or a UniProt
        # accession; keep the source namespace implied by the identifier shape.
        if re.fullmatch(r"ENSG\d+", str(target_raw)):
            target = out.node(target_raw, "Gene", target_raw)
        elif re.fullmatch(r"[A-NR-Z][0-9][A-Z0-9]{3}[0-9]", str(target_raw)):
            target = out.node(_curie(target_raw, "UniProt"), "Protein", target_raw)
    disease = None
    for key in ("diseaseFromSourceMappedId", "diseaseFromSourceId"):
        raw = _value(row, key)
        if not raw:
            continue
        value = _label(raw)
        if ":" not in value and re.match(r"^EFO_\d+$", value):
            value = value.replace("EFO_", "EFO:", 1)
        disease = out.node(_disease_id(value), "Disease", _value(row, "diseaseFromSource") or value)
        if disease:
            break
    out.edge(evidence, "HAS_REPORTED_TARGET", target)
    out.edge(evidence, "HAS_MAPPED_DISEASE", disease)
    if target:
        out.edge(target, "HAS_SOURCE_EVIDENCE", evidence)
    if disease:
        out.edge(disease, "HAS_SOURCE_EVIDENCE", evidence)


def _clinical_trial(out: _Output, row: dict):
    protocol = row.get("protocolSection", row)
    identification = protocol.get("identificationModule", {}) if isinstance(protocol, dict) else {}
    nct = _value(identification, "nctId") if isinstance(identification, dict) else None
    if not nct:
        return
    study = out.node(_curie(nct, "NCT"), "Study", _value(identification, "briefTitle", "officialTitle"))
    membership = row.get("query_membership", [])
    if not isinstance(membership, list):
        return
    for index, item in enumerate(membership):
        if not isinstance(item, dict):
            continue
        terms = item.get("terms")
        if isinstance(terms, list):
            label = "Search batch: " + ", ".join(str(t) for t in terms if isinstance(t, str))
            raw_id = item.get("query_set", str(index))
        else:
            label = _value(item, "term", "query_set")
            raw_id = _value(item, "query_id", "query_set", "term") or str(index)
        query_id = _curie("CTGovQuery:" + re.sub(r"[^A-Za-z0-9_-]+", "-", str(raw_id)))
        query = out.node(query_id, "SearchQuery", label)
        out.edge(study, "RETURNED_BY_QUERY", query)


def _epmc_publication(out: _Output, article_id: Any):
    value = _label(article_id)
    if not value:
        return None
    if value.startswith("MED:"):
        identifier = _curie(value.replace("MED:", "PMID:", 1))
    elif value.startswith("PMC:"):
        identifier = _curie(value.replace("PMC:", "PMCID:", 1))
    elif re.match(r"^(AGR|PPR|MED):", value):
        prefix, local = value.split(":", 1)
        identifier = _curie(f"EPMC:{prefix}-{local}")
    else:
        identifier = _curie("EPMC:" + value)
    return out.node(identifier, "Publication", identifier)


def _publication(out: _Output, source: str, dataset: str, row: dict):
    if dataset == "query_membership":
        article = _epmc_publication(out, row.get("article_id"))
        query = out.node(_curie(_value(row, "query_id"), "EPMCQuery"), "SearchQuery", _value(row, "query_id"))
        out.edge(article, "RETURNED_BY_QUERY", query)
        return
    identifier, title = _publication_id(row)
    if source == "crossref_grin" and not identifier:
        doi = _value(row, "DOI")
        if doi and _DOI.fullmatch(str(doi)):
            identifier = "DOI:" + str(doi).lower()
    if not identifier:
        return
    publication = out.node(identifier, "Publication", title or identifier)
    if source in {"europe_pmc_diseases", "europe_pmc_preprints"}:
        _author_edges(out, row, publication)
    if source == "crossref_grin":
        for author in row.get("author", []) if isinstance(row.get("author"), list) else []:
            if not isinstance(author, dict):
                continue
            raw_orcid = _value(author, "ORCID", "orcid")
            if not raw_orcid:
                continue
            value = str(raw_orcid).removeprefix("https://orcid.org/")
            if _ORCID.fullmatch(value):
                name = " ".join(part for part in (_label(author.get("given")), _label(author.get("family"))) if part)
                person = out.node("ORCID:" + value, "Person", name or value)
                out.edge(person, "AUTHORED", publication)
    references = row.get("reference", [])
    if not isinstance(references, list):
        return
    for ref in references:
        if not isinstance(ref, dict):
            continue
        doi = _value(ref, "DOI", "doi")
        if doi and _DOI.fullmatch(str(doi)):
            target = out.node("DOI:" + str(doi).lower(), "Publication", _value(ref, "article-title") or doi)
            out.edge(publication, "CITES", target)


def _ror(out: _Output, row: dict):
    identifier = _curie(_value(row, "id"))
    names = row.get("names", [])
    label = next((item.get("value") for item in names if isinstance(item, dict) and "label" in item.get("types", [])), None) if isinstance(names, list) else None
    aliases = [item.get("value") for item in names if isinstance(item, dict) and item.get("value") != label] if isinstance(names, list) else []
    org = out.node(identifier, "Organization", label or identifier, aliases)
    relations = row.get("relationships", [])
    for relationship in relations if isinstance(relations, list) else []:
        if not isinstance(relationship, dict):
            continue
        other_id = _curie(_value(relationship, "id"))
        other = out.node(other_id, "Organization", _value(relationship, "label", "name") or other_id)
        rel_type = _label(_value(relationship, "type")).casefold()
        predicate = {"parent": "CHILD_OF_ORGANIZATION", "child": "PARENT_OF_ORGANIZATION",
                     "related": "RELATED_TO_ORGANIZATION"}.get(rel_type)
        if predicate:
            out.edge(org, predicate, other)


def _nih_project(out: _Output, row: dict):
    project_id = _value(row, "appl_id")
    grant = out.node(_curie(project_id, "NIHReporter"), "Grant", _value(row, "project_num", "project_title") or project_id)
    for investigator in row.get("principal_investigators", []) if isinstance(row.get("principal_investigators"), list) else []:
        if not isinstance(investigator, dict) or not investigator.get("profile_id"):
            continue
        person_id = _curie(investigator["profile_id"], "NIHPI")
        person = out.node(person_id, "Person", _value(investigator, "full_name"))
        out.edge(person, "PRINCIPAL_INVESTIGATOR_ON", grant)
    organization = row.get("organization")
    if isinstance(organization, dict):
        ror = next((x.get("id") for x in organization.get("external_ids", []) if isinstance(x, dict) and x.get("type", "").casefold() == "ror"), None)
        if ror:
            org = out.node(_curie(ror), "Organization", _value(organization, "org_name"))
            out.edge(org, "RECEIVED_GRANT", grant)


def _raresource_disease(out: _Output, row: dict):
    identifiers = []
    for key, prefix in (("OMIM", "OMIM"), ("Orphanet", "Orphanet"), ("UMLS", "UMLS"), ("Mesh", "MeSH")):
        value = _value(row, key)
        curie = _curie(value, prefix) if value else None
        if curie:
            identifiers.append(curie)
    disease = out.node(identifiers[0] if identifiers else None, "Disease", _value(row, "Rare Disease Name"),
                       _split_values(_value(row, "Disease Aliases"), separators=r"//"))
    for alternate in identifiers[1:]:
        node = out.node(alternate, "Disease", alternate)
        out.edge(disease, "CROSS_REFERENCED_AS", node)
    genes = _split_values(_value(row, "Associated Genes"))
    # Gene symbols are not stable IDs; only link when this row has a direct stable identifier
    # in the related rare-disease gene record, never by matching this string elsewhere.
    return


def _uniprot(out: _Output, row: dict):
    organism = row.get("organism", {})
    if not isinstance(organism, dict) or organism.get("taxonId") != 9606:
        return
    accession = _value(row, "primaryAccession")
    description = row.get("proteinDescription", {})
    recommended = description.get("recommendedName", {}) if isinstance(description, dict) else {}
    full_name = recommended.get("fullName", {}) if isinstance(recommended, dict) else {}
    label = _value(full_name, "value") if isinstance(full_name, dict) else accession
    protein = out.node(_curie(accession, "UniProt"), "Protein", label)
    for gene_record in row.get("genes", []) if isinstance(row.get("genes"), list) else []:
        if not isinstance(gene_record, dict):
            continue
        gene_name = gene_record.get("geneName", {})
        symbol = _value(gene_name, "value") if isinstance(gene_name, dict) else None
        evidences = gene_name.get("evidences", []) if isinstance(gene_name, dict) else []
        hgnc_id = next((item.get("id") for item in evidences if isinstance(item, dict)
                        and item.get("source") == "HGNC" and item.get("id")), None)
        gene = out.node(_curie(hgnc_id), "Gene", symbol)
        out.edge(gene, "ENCODES", protein)
    for reference in row.get("uniProtKBCrossReferences", []) if isinstance(row.get("uniProtKBCrossReferences"), list) else []:
        if not isinstance(reference, dict):
            continue
        database = reference.get("database")
        value = _value(reference, "id")
        if database == "GeneID" and value:
            gene = out.node(_curie(value, "NCBIGene"), "Gene", value)
            out.edge(gene, "ENCODES", protein)


def _mgi(out: _Output, dataset: str, row: dict):
    if dataset == "hom_allorganism":
        group = out.node(_curie(_value(row, "homology_class"), "MGIHomology"), "HomologyGroup",
                         _value(row, "homology_class"))
        taxon_id = _value(row, "taxon_id")
        marker = out.node(_curie(_value(row, "mouse_mgi_id")), "Gene", _value(row, "symbol"))
        entrez_id = _curie(_value(row, "entrez_id"), "NCBIGene")
        if not marker:
            marker = out.node(entrez_id, "Gene", _value(row, "symbol"))
        out.edge(marker, "MEMBER_OF_HOMOLOGY_GROUP", group)
        if marker and entrez_id and marker != entrez_id:
            entrez = out.node(entrez_id, "Gene", _value(row, "symbol"))
            out.edge(marker, "SAME_AS", entrez)
        if taxon_id:
            taxon = out.node(_curie(taxon_id, "NCBITaxon"), "Species", taxon_id)
            out.edge(marker, "IN_SPECIES", taxon)
    elif dataset == "mgi_phenotypicallele":
        allele = out.node(_curie(_value(row, "allele_id")), "Variant", _value(row, "allele_symbol"))
        marker = out.node(_curie(_value(row, "marker_id")), "Gene", _value(row, "marker_symbol"))
        out.edge(allele, "ALLELE_OF", marker)
        _mgi_phenotypes(out, allele, row.get("phenotype_ids"))
    elif dataset in {"mgi_genepheno", "mgi_geno_diseasedo", "mgi_geno_notdiseasedo"}:
        genotype = out.node(_curie(_value(row, "genotype_id")), "Genotype", _value(row, "allelic_composition"))
        _mgi_phenotypes(out, genotype, row.get("phenotype_id"))
        if dataset == "mgi_geno_diseasedo":
            disease_ids = _split_values(_value(row, "disease_ids"))
            for disease_id in disease_ids:
                disease = out.node(_disease_id(disease_id), "Disease", disease_id)
                out.edge(genotype, "ASSOCIATED_WITH_DISEASE", disease)
        elif dataset == "mgi_geno_notdiseasedo" and _value(row, "disease_ids"):
            # Negative association is explicit and remains a distinct predicate.
            for disease_id in _split_values(row["disease_ids"]):
                disease = out.node(_disease_id(disease_id), "Disease", disease_id)
                out.edge(genotype, "NOT_ASSOCIATED_WITH_DISEASE", disease)
        for marker_id in _split_values(_value(row, "marker_ids")):
            marker = out.node(_curie(marker_id), "Gene", marker_id)
            out.edge(genotype, "HAS_MARKER_GENE", marker)
    elif dataset == "mgi_diseasegenemodel":
        disease = out.node(_disease_id(_value(row, "disease_id")), "Disease", _value(row, "disease_name"))
        model_id = _curie(_value(row, "mouse_mgi_id"))
        model = out.node(model_id, "Gene", _value(row, "mouse_symbol"))
        out.edge(disease, "HAS_MOUSE_MODEL_GENE", model)
        for hgnc_id in _split_values(_value(row, "hgnc_ids")):
            human = out.node(_curie(hgnc_id), "Gene", _value(row, "human_symbol"))
            out.edge(disease, "HAS_REPORTED_HUMAN_GENE", human)
    elif dataset == "mgi_diseasemousemodel":
        disease = out.node(_disease_id(_value(row, "disease_id")), "Disease", _value(row, "disease_name"))
        allele = out.node(_curie(_value(row, "allele_id")), "Variant", _value(row, "allele_symbol"))
        marker = out.node(_curie(_value(row, "marker_id")), "Gene", _value(row, "marker_symbol"))
        out.edge(allele, "ALLELE_OF", marker)
        if not _value(row, "not_model"):
            out.edge(allele, "MODELS_DISEASE", disease)
    elif dataset == "mgi_strain":
        out.node(_curie(_value(row, "strain_id")), "Strain", _value(row, "strain_name"))


def _mgi_phenotypes(out: _Output, subject: str | None, value: Any):
    for phenotype_id in _split_values(value):
        phenotype = out.node(_curie(phenotype_id), "Phenotype", phenotype_id)
        out.edge(subject, "HAS_MODEL_PHENOTYPE", phenotype)
