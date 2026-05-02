"""
Agent 2: Document Extraction Agent

Extracts structured information from uploaded documents.
For test cases with pre-provided content, uses structured data directly.
Handles failures gracefully with confidence degradation.
"""
from __future__ import annotations

import os, json, traceback
from datetime import datetime, timezone
from typing import Any

from models.claim import ClaimSubmission, DocumentUpload
from models.decision import ExtractedDocument, ExtractedField, TraceStep, TraceStepStatus
from agents.state import ClaimPipelineState
from services.policy_engine import get_policy_engine


def _extract_from_content(doc: DocumentUpload) -> ExtractedDocument:
    """Extract structured data from pre-provided document content or use Vision LLM extraction."""
    fields: list[ExtractedField] = []
    
    if doc.content:
        # User provided manual structured data
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
        
        return ExtractedDocument(
            file_id=doc.file_id, 
            document_type=doc.actual_type.value, 
            fields=fields, 
            extraction_confidence=0.95 if fields else 0.5
        )
    else:
        # Actual LLM Extraction from the file
        from services.llm_service import extract_document_data
        
        if not doc.file_path:
            return ExtractedDocument(
                file_id=doc.file_id, 
                document_type=doc.actual_type.value, 
                fields=[], 
                extraction_confidence=0.0
            )

        extraction_result = extract_document_data(doc.file_path, doc.actual_type.value)
        
        for name, value in extraction_result.extracted_fields.items():
            if value is not None:
                fields.append(ExtractedField(
                    field_name=name, 
                    value=value, 
                    confidence=extraction_result.confidence_score, 
                    source_document=doc.file_id
                ))
                
        return ExtractedDocument(
            file_id=doc.file_id, 
            document_type=doc.actual_type.value, 
            fields=fields, 
            extraction_confidence=extraction_result.confidence_score,
            document_flags=extraction_result.document_flags
        )


def document_extraction_agent(state: ClaimPipelineState) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    claim = ClaimSubmission(**state["claim"])
    documents = [DocumentUpload(**d) for d in state["documents"]]
    simulate_failure = claim.simulate_component_failure

    extracted: list[ExtractedDocument] = []
    component_failures = list(state.get("component_failures", []))
    warnings: list[str] = []
    
    engine = get_policy_engine()
    member = engine.get_member(claim.member_id)

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

    diagnosis = treatment = None
    line_items = None
    extracted_hospital_name = None
    extracted_patient_name = None
    
    for ext_doc in extracted:
        for field in ext_doc.fields:
            if field.field_name == "diagnosis" and not diagnosis: diagnosis = field.value
            if field.field_name == "treatment" and not treatment: treatment = field.value
            if field.field_name == "hospital_name" and not extracted_hospital_name: extracted_hospital_name = field.value
            if field.field_name == "patient_name" and not extracted_patient_name: extracted_patient_name = field.value
            if field.field_name == "line_items" and not line_items: line_items = field.value
            
        # Check mismatches for this specific document
        doc_hospital = next((f.value for f in ext_doc.fields if f.field_name == "hospital_name"), None)
        doc_patient = next((f.value for f in ext_doc.fields if f.field_name == "patient_name"), None)
        
        mismatch_found = False
        if doc_hospital and claim.hospital_name:
            h_ext = doc_hospital.lower().strip()
            h_claim = claim.hospital_name.lower().strip()
            if h_ext not in h_claim and h_claim not in h_ext:
                warnings.append(f"Hospital name mismatch in {ext_doc.document_type}: Claim says '{claim.hospital_name}', document says '{doc_hospital}'.")
                mismatch_found = True
                
        if doc_patient and member and member.name:
            p_ext = doc_patient.lower().strip()
            p_mem = member.name.lower().strip()
            if p_ext not in p_mem and p_mem not in p_ext:
                warnings.append(f"Patient name mismatch in {ext_doc.document_type}: Policy says '{member.name}', document says '{doc_patient}'.")
                mismatch_found = True
                
        if mismatch_found:
            # Reduce confidence score instead of halting
            ext_doc.extraction_confidence = max(0.1, ext_doc.extraction_confidence - 0.3)
            if "Name Mismatch" not in ext_doc.warnings:
                ext_doc.warnings.append("Name Mismatch")

    completed_at = datetime.now(timezone.utc)
    avg_conf = sum(e.extraction_confidence for e in extracted) / len(extracted) if extracted else 0
    trace_step = TraceStep(
        agent_name="document_extractor", display_name="🔍 Document Extraction",
        status=TraceStepStatus.WARNING if simulate_failure or warnings else TraceStepStatus.SUCCESS,
        started_at=started_at, completed_at=completed_at,
        duration_ms=(completed_at - started_at).total_seconds() * 1000,
        input_summary={"documents_count": len(documents), "simulated_failure": simulate_failure},
        output_summary={"extracted_count": len(extracted), "avg_confidence": round(avg_conf, 2), "diagnosis": diagnosis, "hospital": extracted_hospital_name},
        warnings=warnings,
        message=f"Component failure simulated — degraded extraction." if simulate_failure else f"Extracted from {len(extracted)} doc(s), avg confidence {avg_conf:.0%}.",
    )

    # ── Check for missing info ───────────────────────────────────────────
    should_stop = False
    has_prescription = any(doc.actual_type.value == "PRESCRIPTION" for doc in documents)
    has_missing_flags = any("MISSING_FIELDS" in getattr(doc, "document_flags", []) for doc in extracted)
    
    if has_prescription and not diagnosis:
        should_stop = True
        warnings.append("Critical information missing: Diagnosis could not be extracted from the prescription.")
        trace_step.status = TraceStepStatus.FAILED
        trace_step.message = "Extraction failed: Diagnosis missing."
    elif has_missing_flags:
        should_stop = True
        warnings.append("Incomplete extraction: Some expected fields are missing from the documents.")
        trace_step.status = TraceStepStatus.FAILED
        trace_step.message = "Extraction incomplete: Missing fields detected."
        
    if warnings and trace_step.status == TraceStepStatus.SUCCESS:
        trace_step.status = TraceStepStatus.WARNING
        if any("mismatch" in w for w in warnings):
            trace_step.message = "Extraction completed with name mismatches (reduced confidence)."
    # print('extractor complete!!----------------------------------------')
    return {
        "extracted_data": [e.model_dump() for e in extracted],
        "diagnosis": diagnosis, "treatment": treatment,
        "hospital_name": extracted_hospital_name or claim.hospital_name,
        "line_items": line_items, "component_failures": component_failures,
        "should_stop": should_stop,
        "trace": state.get("trace", []) + [trace_step.model_dump()],
    }
