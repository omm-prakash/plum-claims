"""
Decision and trace models — captures the output of the claims pipeline
including the decision, amounts, confidence, and a full audit trail.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class ClaimDecision(str, Enum):
    APPROVED = "APPROVED"
    PARTIAL = "PARTIAL"
    REJECTED = "REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class TraceStepStatus(str, Enum):
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class TraceStep(BaseModel):
    """A single step in the processing trace — one per agent."""
    agent_name: str
    display_name: str
    status: TraceStepStatus = TraceStepStatus.SUCCESS
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[float] = None
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    checks_performed: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    message: Optional[str] = None


class LineItemDecision(BaseModel):
    """Decision for an individual line item on a bill."""
    description: str
    claimed_amount: float
    approved_amount: float
    status: str  # "APPROVED", "REJECTED", "EXCLUDED"
    reason: Optional[str] = None


class AmountBreakdown(BaseModel):
    """Detailed breakdown of how the approved amount was calculated."""
    original_amount: float
    eligible_amount: float
    network_discount_applied: float = 0
    amount_after_discount: float = 0
    copay_amount: float = 0
    amount_after_copay: float = 0
    sub_limit_applied: Optional[float] = None
    per_claim_limit_applied: Optional[float] = None
    annual_limit_remaining: Optional[float] = None
    final_approved_amount: float = 0
    line_item_decisions: list[LineItemDecision] = Field(default_factory=list)
    calculation_steps: list[str] = Field(default_factory=list)


class DocVerificationResult(BaseModel):
    """Result from the document verification agent."""
    passed: bool = False
    needs_manual_review: bool = False
    missing_documents: list[str] = Field(default_factory=list)
    wrong_documents: list[dict[str, Any]] = Field(default_factory=list)
    unreadable_documents: list[dict[str, Any]] = Field(default_factory=list)
    patient_name_mismatch: Optional[dict[str, Any]] = None
    error_message: Optional[str] = None
    details: list[str] = Field(default_factory=list)


class ExtractedField(BaseModel):
    """A single extracted field with confidence."""
    field_name: str
    value: Any
    confidence: float = 1.0
    source_document: Optional[str] = None


class ExtractedDocument(BaseModel):
    """Structured data extracted from a single document."""
    file_id: str
    document_type: str
    fields: list[ExtractedField] = Field(default_factory=list)
    raw_text: Optional[str] = None
    extraction_confidence: float = 1.0
    warnings: list[str] = Field(default_factory=list)
    document_flags: list[str] = Field(default_factory=list)


class PolicyCheckResult(BaseModel):
    """Result from the policy validation agent."""
    eligible: bool = True
    violations: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    checks_performed: list[dict[str, Any]] = Field(default_factory=list)


class FraudCheckResult(BaseModel):
    """Result from the fraud detection agent."""
    fraud_score: float = 0.0
    signals: list[dict[str, Any]] = Field(default_factory=list)
    requires_manual_review: bool = False
    details: list[str] = Field(default_factory=list)


class DecisionResult(BaseModel):
    """
    The final output of the claims processing pipeline.
    This is what the ops team and member see.
    """
    claim_id: str
    decision: ClaimDecision
    approved_amount: float = 0
    claimed_amount: float = 0
    confidence_score: float = 0.0
    reasons: list[str] = Field(default_factory=list)
    explanation: str = ""
    amount_breakdown: Optional[AmountBreakdown] = None
    doc_verification: Optional[DocVerificationResult] = None
    policy_check: Optional[PolicyCheckResult] = None
    fraud_check: Optional[FraudCheckResult] = None
    trace: list[TraceStep] = Field(default_factory=list)
    component_failures: list[str] = Field(default_factory=list)
    requires_manual_review_note: Optional[str] = None
    processed_at: datetime = Field(default_factory=datetime.utcnow)
