"""
Claim data models — defines the structure of a claim submission,
uploaded documents, and related enums.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ── Enums ────────────────────────────────────────────────────────────────────

class ClaimCategory(str, Enum):
    CONSULTATION = "CONSULTATION"
    DIAGNOSTIC = "DIAGNOSTIC"
    PHARMACY = "PHARMACY"
    DENTAL = "DENTAL"
    VISION = "VISION"
    ALTERNATIVE_MEDICINE = "ALTERNATIVE_MEDICINE"


class DocumentType(str, Enum):
    PRESCRIPTION = "PRESCRIPTION"
    HOSPITAL_BILL = "HOSPITAL_BILL"
    LAB_REPORT = "LAB_REPORT"
    PHARMACY_BILL = "PHARMACY_BILL"
    DIAGNOSTIC_REPORT = "DIAGNOSTIC_REPORT"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    DENTAL_REPORT = "DENTAL_REPORT"


class DocumentQuality(str, Enum):
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    UNREADABLE = "UNREADABLE"


# ── Document Models ──────────────────────────────────────────────────────────

class DocumentContent(BaseModel):
    """Structured content extracted from or provided with a document."""
    doctor_name: Optional[str] = None
    doctor_registration: Optional[str] = None
    patient_name: Optional[str] = None
    date: Optional[str] = None
    diagnosis: Optional[str] = None
    treatment: Optional[str] = None
    medicines: Optional[list[str]] = None
    tests_ordered: Optional[list[str]] = None
    hospital_name: Optional[str] = None
    line_items: Optional[list[dict[str, Any]]] = None
    total: Optional[float] = None
    test_name: Optional[str] = None


class DocumentUpload(BaseModel):
    """A single document uploaded as part of a claim."""
    file_id: str = Field(default_factory=lambda: f"F{uuid.uuid4().hex[:6].upper()}")
    file_name: Optional[str] = None
    actual_type: DocumentType
    quality: DocumentQuality = DocumentQuality.GOOD
    patient_name_on_doc: Optional[str] = None
    content: Optional[DocumentContent] = None
    file_path: Optional[str] = None  # Path to uploaded file on disk


class ClaimHistoryEntry(BaseModel):
    """A previous claim in the member's history."""
    claim_id: str
    date: str
    amount: float
    provider: Optional[str] = None


# ── Claim Submission ─────────────────────────────────────────────────────────

class ClaimSubmission(BaseModel):
    """
    Represents a claim submission from a member.
    This is the primary input to the processing pipeline.
    """
    claim_id: str = Field(default_factory=lambda: f"CLM_{uuid.uuid4().hex[:8].upper()}")
    member_id: str
    policy_id: str = "PLUM_GHI_2024"
    claim_category: ClaimCategory
    treatment_date: str  # ISO format YYYY-MM-DD
    claimed_amount: float
    hospital_name: Optional[str] = None
    ytd_claims_amount: float = 0.0
    claims_history: list[ClaimHistoryEntry] = Field(default_factory=list)
    documents: list[DocumentUpload] = Field(default_factory=list)
    simulate_component_failure: bool = False
    submitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("claimed_amount")
    @classmethod
    def amount_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Claimed amount must be positive")
        return v
