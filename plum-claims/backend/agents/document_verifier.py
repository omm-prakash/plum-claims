"""
Agent 1: Document Verification Agent

Validates that the correct document types have been uploaded for the claim
category. Catches problems early:
- Wrong document types uploaded
- Missing required documents
- Unreadable documents
- Patient name mismatches across documents

If any issue is found, sets should_stop=True to halt the pipeline
and returns a specific, actionable error message.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from models.claim import ClaimCategory, ClaimSubmission, DocumentUpload, DocumentType, DocumentQuality
from models.decision import DocVerificationResult, TraceStep, TraceStepStatus
from services.policy_engine import get_policy_engine
from agents.state import ClaimPipelineState
from services.llm_service import analyze_document


def document_verification_agent(state: ClaimPipelineState) -> dict[str, Any]:
    """
    Verify uploaded documents against policy requirements.
    
    Input: claim category + uploaded documents
    Output: DocVerificationResult with pass/fail + specific error messages
    """
    started_at = datetime.utcnow()
    engine = get_policy_engine()
    claim = ClaimSubmission(**state["claim"])
    documents = [DocumentUpload(**d) for d in state["documents"]]

    result = DocVerificationResult(passed=True)
    checks: list[dict[str, Any]] = []

    # ── Check 1: Required document types ─────────────────────────────────
    doc_reqs = engine.get_document_requirements(claim.claim_category.value)
    if doc_reqs:
        valid_types = set(doc_reqs.required + doc_reqs.optional)
        # Drop documents that are neither required nor optional
        documents = [d for d in documents if d.actual_type.value in valid_types]
        state["documents"] = [d.model_dump() for d in documents]

        uploaded_types = [d.actual_type.value for d in documents]
        required_types = doc_reqs.required

        for req_type in required_types:
            check = {"check": f"Required document: {req_type}", "status": "PASS"}
            if req_type not in uploaded_types:
                check["status"] = "FAIL"
                # Find what was uploaded instead
                other_types = list(set(uploaded_types))
                result.passed = False
                result.missing_documents.append(req_type)

                # Build specific error message
                uploaded_str = ", ".join(
                    f"{t.replace('_', ' ').title()}" for t in other_types
                )
                required_str = req_type.replace("_", " ").title()
                result.wrong_documents.append({
                    "expected": req_type,
                    "uploaded_instead": other_types,
                    "message": (
                        f"A {required_str} is required for {claim.claim_category.value.replace('_', ' ').title()} claims, "
                        f"but was not found. You uploaded: {uploaded_str}. "
                        f"Please upload a valid {required_str} and resubmit."
                    )
                })
            checks.append(check)

    # ── Check 2: Document quality / readability ──────────────────────────
    for doc in documents:
        # Use Vision LLM to verify document quality and patient name if a file was uploaded
        if doc.file_path:
            analysis = analyze_document(doc.file_path)
            try:
                doc.quality = DocumentQuality(analysis.quality)
            except ValueError:
                doc.quality = DocumentQuality.POOR # fallback
            doc.patient_name_on_doc = analysis.patient_name

            # Check for document type mismatch from LLM
            if analysis.detected_type != "UNKNOWN" and analysis.detected_type != doc.actual_type.value:
                result.passed = False
                doc_type_display = doc.actual_type.value.replace("_", " ").title()
                detected_display = analysis.detected_type.replace("_", " ").title()
                
                result.wrong_documents.append({
                    "expected": doc.actual_type.value,
                    "uploaded_instead": [analysis.detected_type],
                    "message": (
                        f"Document type mismatch: You selected {doc_type_display} "
                        f"but our system detected a {detected_display}. "
                        f"Please select the correct document type and resubmit."
                    )
                })
                check = {
                    "check": f"Document Type Match: {doc.file_id}",
                    "status": "FAIL - Mismatch"
                }
                checks.append(check)
                continue # skip quality check if type doesn't match
            print(analysis.detected_type )

        check = {
            "check": f"Document quality: {doc.file_id} ({doc.actual_type.value})",
            "status": "PASS"
        }
        if doc.quality and doc.quality.value == "UNREADABLE":
            check["status"] = "FAIL"
            result.passed = False
            doc_type_display = doc.actual_type.value.replace("_", " ").title()
            result.unreadable_documents.append({
                "file_id": doc.file_id,
                "file_name": doc.file_name or doc.file_id,
                "document_type": doc.actual_type.value,
                "message": (
                    f"Your {doc_type_display} ({doc.file_name or doc.file_id}) could not be read — "
                    f"the image appears to be blurry or too low quality. "
                    f"Please re-upload a clearer photo or scan of your {doc_type_display}."
                )
            })
        checks.append(check)

    # ── Check 3: Patient name consistency across documents ───────────────
    patient_names: dict[str, list[str]] = {}
    for doc in documents:
        name = None
        if doc.patient_name_on_doc:
            name = doc.patient_name_on_doc.strip()
        elif doc.content and doc.content.patient_name:
            name = doc.content.patient_name.strip()
        if name:
            patient_names.setdefault(name, []).append(
                f"{doc.actual_type.value} ({doc.file_id})"
            )

    if len(patient_names) > 1:
        check = {"check": "Patient name consistency", "status": "FAIL"}
        result.passed = False
        names_detail = []
        for name, docs_list in patient_names.items():
            names_detail.append(f"'{name}' on {', '.join(docs_list)}")
        names_str = "; ".join(names_detail)
        result.patient_name_mismatch = {
            "names_found": dict(patient_names),
            "message": (
                f"The documents belong to different patients: {names_str}. "
                f"All documents for a claim must be for the same patient. "
                f"Please upload documents for a single patient."
            )
        }
        checks.append(check)
    elif len(patient_names) == 1:
        checks.append({"check": "Patient name consistency", "status": "PASS"})

    # ── Build error message ──────────────────────────────────────────────
    if not result.passed:
        messages = []
        for wd in result.wrong_documents:
            messages.append(wd["message"])
        for ud in result.unreadable_documents:
            messages.append(ud["message"])
        if result.patient_name_mismatch:
            messages.append(result.patient_name_mismatch["message"])
        result.error_message = " | ".join(messages)

    # ── Build trace step ─────────────────────────────────────────────────
    completed_at = datetime.utcnow()
    trace_step = TraceStep(
        agent_name="document_verifier",
        display_name="📄 Document Verification",
        status=TraceStepStatus.SUCCESS if result.passed else TraceStepStatus.FAILED,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=(completed_at - started_at).total_seconds() * 1000,
        input_summary={
            "claim_category": claim.claim_category.value,
            "documents_count": len(documents),
            "document_types": [d.actual_type.value for d in documents],
        },
        output_summary={
            "passed": result.passed,
            "issues_found": len(result.wrong_documents) + len(result.unreadable_documents) + (1 if result.patient_name_mismatch else 0),
        },
        checks_performed=checks,
        message=result.error_message if not result.passed else "All documents verified successfully.",
    )

    return {
        "doc_verification": result.model_dump(),
        "should_stop": not result.passed,
        "trace": state.get("trace", []) + [trace_step.model_dump()],
    }
