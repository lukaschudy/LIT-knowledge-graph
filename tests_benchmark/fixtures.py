"""Entirely invented test data. No biomedical facts or human annotations."""
from copy import deepcopy

from atlas.benchmark.contracts import VERSION, digest


def example():
    units = []
    documents = []
    annotations = []
    predictions = []
    for index in (1, 2):
        doc_id = f"SYNTHETIC-DOC-{index}"
        text = "SYNTHETIC ONLY. Variant p.Ala1Val current 30 pA; WT 100 pA; SEM 2 pA; n=5 cells."
        unit = {"unit_id": f"synthetic-unit-{index}", "document_id": doc_id,
                "kind": "paragraph", "locator": "synthetic paragraph 1", "text": text}
        units.append(unit)
        documents.append({"document_id": doc_id, "study_id": f"synthetic-study-{index}",
                          "split": "development", "known_development": True, "grouping_reviewed": True,
                          "source_sha256": digest([unit]), "strata": ["synthetic", "paragraph"]})
        span = {"unit_id": unit["unit_id"], "start": 0, "end": len(text), "quote": text}
        obs = {"id": "reference-1", "gene": "SYNTHETIC_GENE", "variant": "p.Ala1Val",
               "sequence_context": None, "assay": "synthetic current assay", "property": "current",
               "measurement_type": "measured", "value": "30", "unit": "pA",
               "comparator": {"label": "WT", "value": "100", "unit": "pA"},
               "conditions": {"receptor": None, "system": "synthetic cells", "protocol": None},
               "uncertainty": {"type": "SEM", "value": "2"},
               "sample_size": {"value": 5, "unit": "cells"}, "evidence_sets": [[span]]}
        annotations.append({"document_id": doc_id, "coverage": "complete",
                            "review": {"annotators": [], "adjudicator": None, "expert_reviewed": False},
                            "observations": [obs],
                            "decisions": [{"case_id": "synthetic-question-1", "question": "Does the synthetic assay support lower current than WT?",
                                           "label": "supports", "observation_ids": [obs["id"]], "author_interpretation": None}]})
        predicted = deepcopy(obs)
        predicted["id"] = "prediction-1"
        predicted["evidence"] = predicted.pop("evidence_sets")[0]
        predictions.append({"document_id": doc_id, "status": "complete", "observations": [predicted],
                            "decisions": [{"case_id": "synthetic-question-1", "label": "supports", "observation_ids": [predicted["id"]]}]})
    manifest = {"schema_version": VERSION, "benchmark_id": "SYNTHETIC-MACHINERY-ONLY", "state": "frozen",
                "synthetic": True, "scope": "Invented records for software tests; not a scientific benchmark.", "documents": documents}
    reference = {"schema_version": VERSION, "manifest_sha256": digest(manifest), "split": "development", "documents": annotations}
    config = {"models": [], "generator": "tests_benchmark.fixtures.example", "model_calls": 0,
              "retrieval": {"enabled": False, "max_rounds": 0}}
    predicted = {"schema_version": VERSION, "manifest_sha256": digest(manifest), "split": "development",
                 "run": {"id": "synthetic-perfect", "mode": "extraction", "code_commit": "0" * 40,
                         "prompt_sha256": digest("No prompt or model; deterministic invented fixtures"),
                         "configuration": config, "configuration_sha256": digest(config),
                         "input_tokens": 0, "output_tokens": 0, "cost_usd": "0", "elapsed_seconds": None},
                 "documents": predictions}
    return manifest, {"schema_version": VERSION, "units": units}, reference, predicted
