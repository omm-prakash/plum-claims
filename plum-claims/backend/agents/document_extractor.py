"""
Agent 2: Document Extraction Agent

Extracts structured information from uploaded documents.
For test cases with pre-provided content, uses structured data directly.
Handles failures gracefully with confidence degradation.
"""
from __future__ import annotations

import os, json, traceback
from datetime import datetime
from typing import Any

from models.claim import ClaimSubmission, DocumentUpload
from models.decision import ExtractedDocument, ExtractedField, TraceStep, TraceStepStatus
from agents.state import ClaimPipelineState


def _extract_from_content(doc: DocumentUpload) -> ExtractedDocument:
    """Extract structured data from pre-provided document content."""
    fields: list[ExtractedField] = []
    if doc.content:
        c = doc.content
        for name, value in [
            ("doctor_name", c.doctor_name), ("doctor_registration", c.doctor_registration),
            ("patient_name", c.patient_name), ("date", c.date),
            ("diagnosis", c.diagnosis), ("treatment", c.treatment),
            ("medicines", c.medicines), ("tests_ordered", c.tests_ordered),
            ("hospital_name", c.hospital_name), ("total", c.total),
            ("line_items", c.line_items), ("test_name", c.test_name),
        ]:
            if value is not None:
                fields.append(ExtractedField(field_name=name, value=value, confidence=0.95, source_document=doc.file_id))
    return ExtractedDocument(file_id=doc.file_id, document_type=doc.actual_type.value, fields=fields, extraction_confidence=0.95 if fields else 0.5)


def document_extraction_agent(state: ClaimPipelineState) -> dict[str, Any]:
    started_at = datetime.utcnow()
    claim = ClaimSubmission(**state["claim"])
    documents = [DocumentUpload(**d) for d in state["documents"]]
    simulate_failure = claim.simulate_component_failure

    extracted: list[ExtractedDocument] = []
    component_failures = list(state.get("component_failures", []))
    warnings: list[str] = []

    if simulate_failure:
        component_failures.append("document_extractor")
        warnings.append("Document extraction component experienced a failure. Proceeding with available data. Manual review recommended.")
        for doc in documents:
            if doc.content:
                ext_doc = _extract_from_content(doc)
                ext_doc.extraction_confidence *= 0.5
                ext_doc.warnings.append("Extracted under degraded mode")
                extracted.append(ext_doc)
    else:
        for doc in documents:
            try:
                extracted.append(_extract_from_content(doc))
            except Exception as e:
                warnings.append(f"Failed to extract from {doc.file_id}: {e}")
                extracted.append(ExtractedDocument(file_id=doc.file_id, document_type=doc.actual_type.value, extraction_confidence=0.3, warnings=[str(e)]))

    diagnosis = treatment = hospital_name = None
    line_items = None
    hospital_name = state.get("hospital_name")
    for ext_doc in extracted:
        for field in ext_doc.fields:
            if field.field_name == "diagnosis" and not diagnosis: diagnosis = field.value
            if field.field_name == "treatment" and not treatment: treatment = field.value
            if field.field_name == "hospital_name" and not hospital_name: hospital_name = field.value
            if field.field_name == "line_items" and not line_items: line_items = field.value

    completed_at = datetime.utcnow()
    avg_conf = sum(e.extraction_confidence for e in extracted) / len(extracted) if extracted else 0
    trace_step = TraceStep(
        agent_name="document_extractor", display_name="🔍 Document Extraction",
        status=TraceStepStatus.WARNING if simulate_failure or warnings else TraceStepStatus.SUCCESS,
        started_at=started_at, completed_at=completed_at,
        duration_ms=(completed_at - started_at).total_seconds() * 1000,
        input_summary={"documents_count": len(documents), "simulated_failure": simulate_failure},
        output_summary={"extracted_count": len(extracted), "avg_confidence": round(avg_conf, 2), "diagnosis": diagnosis, "hospital": hospital_name},
        warnings=warnings,
        message=f"Component failure simulated — degraded extraction." if simulate_failure else f"Extracted from {len(extracted)} doc(s), avg confidence {avg_conf:.0%}.",
    )

    return {
        "extracted_data": [e.model_dump() for e in extracted],
        "diagnosis": diagnosis, "treatment": treatment,
        "hospital_name": hospital_name or claim.hospital_name,
        "line_items": line_items, "component_failures": component_failures,
        "trace": state.get("trace", []) + [trace_step.model_dump()],
    }
