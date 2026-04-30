"""
Pipeline State — the shared state schema that flows through the
LangGraph multi-agent pipeline. Each agent reads from and writes to this state.
"""
from __future__ import annotations

from typing import Any, Optional, TypedDict

from models.claim import ClaimSubmission, DocumentUpload
from models.decision import (
    AmountBreakdown,
    DecisionResult,
    DocVerificationResult,
    ExtractedDocument,
    FraudCheckResult,
    PolicyCheckResult,
    TraceStep,
)


class ClaimPipelineState(TypedDict, total=False):
    """
    The shared state that flows through the claims processing pipeline.
    Each agent reads its inputs from this state and writes its outputs back.
    """
    # ── Input (set once at the start) ────────────────────────────────────
    claim: dict[str, Any]  # Serialized ClaimSubmission
    documents: list[dict[str, Any]]  # Serialized DocumentUpload list

    # ── Agent Outputs (accumulated as pipeline progresses) ───────────────
    doc_verification: Optional[dict[str, Any]]
    extracted_data: Optional[list[dict[str, Any]]]
    policy_check: Optional[dict[str, Any]]
    amount_calc: Optional[dict[str, Any]]
    fraud_check: Optional[dict[str, Any]]

    # ── Final Decision ───────────────────────────────────────────────────
    decision: Optional[dict[str, Any]]

    # ── Trace & Control ──────────────────────────────────────────────────
    trace: list[dict[str, Any]]
    errors: list[str]
    should_stop: bool
    component_failures: list[str]
    hospital_name: Optional[str]
    diagnosis: Optional[str]
    treatment: Optional[str]
    line_items: Optional[list[dict[str, Any]]]
