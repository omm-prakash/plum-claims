"""
Unit tests for the multi-agent pipeline.
Tests each agent function and the full pipeline integration.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.claim import (
    ClaimSubmission, ClaimCategory, DocumentUpload, DocumentType,
    DocumentQuality, DocumentContent, ClaimHistoryEntry,
)
from agents.document_verifier import document_verification_agent
from agents.document_extractor import document_extraction_agent
from agents.policy_validator import policy_validation_agent
from agents.amount_calculator import amount_calculation_agent
from agents.fraud_detector import fraud_detection_agent
from agents.decision_maker import decision_maker_agent
from agents.graph import process_claim


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_claim(**kwargs):
    defaults = {
        "member_id": "EMP001",
        "claim_category": ClaimCategory.CONSULTATION,
        "treatment_date": "2024-11-01",
        "claimed_amount": 1500,
        "documents": [],
    }
    defaults.update(kwargs)
    return ClaimSubmission(**defaults)


def _initial_state(claim, **extra):
    state = {
        "claim": claim.model_dump(),
        "documents": [d.model_dump() for d in claim.documents],
        "doc_verification": None,
        "extracted_data": None,
        "policy_check": None,
        "amount_calc": None,
        "fraud_check": None,
        "decision": None,
        "trace": [],
        "errors": [],
        "should_stop": False,
        "component_failures": [],
        "hospital_name": claim.hospital_name,
        "diagnosis": None,
        "treatment": None,
        "line_items": None,
    }
    state.update(extra)
    return state


# ── Document Verification Tests ─────────────────────────────────────────────

class TestDocumentVerifier:
    def test_correct_documents_pass(self):
        claim = _make_claim(documents=[
            DocumentUpload(actual_type=DocumentType.PRESCRIPTION,
                          content=DocumentContent(patient_name="Rajesh Kumar")),
            DocumentUpload(actual_type=DocumentType.HOSPITAL_BILL,
                          content=DocumentContent(patient_name="Rajesh Kumar")),
        ])
        state = _initial_state(claim)
        result = document_verification_agent(state)
        assert result["doc_verification"]["passed"] is True
        assert result["should_stop"] is False

    def test_missing_required_document_fails(self):
        claim = _make_claim(documents=[
            DocumentUpload(actual_type=DocumentType.PRESCRIPTION),
            DocumentUpload(actual_type=DocumentType.PRESCRIPTION),
        ])
        state = _initial_state(claim)
        result = document_verification_agent(state)
        assert result["doc_verification"]["passed"] is False
        assert result["should_stop"] is True
        assert "HOSPITAL_BILL" in result["doc_verification"]["missing_documents"]

    def test_unreadable_document_fails(self):
        claim = _make_claim(
            claim_category=ClaimCategory.PHARMACY,
            documents=[
                DocumentUpload(actual_type=DocumentType.PRESCRIPTION, quality=DocumentQuality.GOOD),
                DocumentUpload(actual_type=DocumentType.PHARMACY_BILL, quality=DocumentQuality.UNREADABLE),
            ]
        )
        state = _initial_state(claim)
        result = document_verification_agent(state)
        assert result["doc_verification"]["passed"] is False
        assert len(result["doc_verification"]["unreadable_documents"]) == 1

    def test_patient_name_mismatch_fails(self):
        claim = _make_claim(documents=[
            DocumentUpload(actual_type=DocumentType.PRESCRIPTION,
                          patient_name_on_doc="Rajesh Kumar"),
            DocumentUpload(actual_type=DocumentType.HOSPITAL_BILL,
                          patient_name_on_doc="Arjun Mehta"),
        ])
        state = _initial_state(claim)
        result = document_verification_agent(state)
        assert result["doc_verification"]["passed"] is False
        assert result["doc_verification"]["patient_name_mismatch"] is not None


# ── Document Extractor Tests ────────────────────────────────────────────────

class TestDocumentExtractor:
    def test_extracts_from_content(self):
        claim = _make_claim(documents=[
            DocumentUpload(actual_type=DocumentType.PRESCRIPTION,
                          content=DocumentContent(
                              doctor_name="Dr. Arun Sharma",
                              diagnosis="Viral Fever",
                              patient_name="Rajesh Kumar",
                          )),
        ])
        state = _initial_state(claim)
        result = document_extraction_agent(state)
        assert len(result["extracted_data"]) == 1
        assert result["diagnosis"] == "Viral Fever"

    def test_degraded_mode_on_failure(self):
        claim = _make_claim(
            simulate_component_failure=True,
            documents=[
                DocumentUpload(actual_type=DocumentType.PRESCRIPTION,
                              content=DocumentContent(diagnosis="Viral Fever")),
            ]
        )
        state = _initial_state(claim)
        result = document_extraction_agent(state)
        assert "document_extractor" in result["component_failures"]
        # Confidence should be reduced in degraded mode
        extracted = result["extracted_data"][0]
        assert extracted["extraction_confidence"] < 0.95


# ── Amount Calculator Tests ─────────────────────────────────────────────────

class TestAmountCalculator:
    def test_network_discount_before_copay(self):
        """TC010: Network discount (20%) applied first, then co-pay (10%)."""
        claim = _make_claim(
            claimed_amount=4500,
            hospital_name="Apollo Hospitals",
        )
        state = _initial_state(claim, hospital_name="Apollo Hospitals")
        state["policy_check"] = {"eligible": True, "violations": []}
        state["line_items"] = [
            {"description": "Consultation Fee", "amount": 1500},
            {"description": "Medicines", "amount": 3000},
        ]
        result = amount_calculation_agent(state)
        breakdown = result["amount_calc"]
        # 4500 * 0.8 = 3600 (after 20% discount), 3600 * 0.9 = 3240 (after 10% copay)
        assert breakdown["final_approved_amount"] == 3240

    def test_dental_partial_exclusion(self):
        """TC006: Root canal approved, teeth whitening excluded."""
        claim = _make_claim(
            claim_category=ClaimCategory.DENTAL,
            claimed_amount=12000,
        )
        state = _initial_state(claim)
        state["policy_check"] = {
            "eligible": False,
            "violations": [{
                "code": "EXCLUDED_CONDITION",
                "message": "Teeth whitening excluded",
                "excluded_items": ["Teeth Whitening"],
            }],
        }
        state["line_items"] = [
            {"description": "Root Canal Treatment", "amount": 8000},
            {"description": "Teeth Whitening", "amount": 4000},
        ]
        result = amount_calculation_agent(state)
        breakdown = result["amount_calc"]
        assert breakdown["final_approved_amount"] == 8000
        li = breakdown["line_item_decisions"]
        assert any(d["status"] == "EXCLUDED" for d in li)
        assert any(d["status"] == "APPROVED" for d in li)

    def test_hard_rejection_zero_amount(self):
        claim = _make_claim(claimed_amount=7500)
        state = _initial_state(claim)
        state["policy_check"] = {
            "violations": [{"code": "PER_CLAIM_EXCEEDED", "message": "Exceeds limit"}],
        }
        result = amount_calculation_agent(state)
        assert result["amount_calc"]["final_approved_amount"] == 0


# ── Fraud Detector Tests ────────────────────────────────────────────────────

class TestFraudDetector:
    def test_no_fraud_signals(self):
        claim = _make_claim(claimed_amount=1500)
        state = _initial_state(claim)
        result = fraud_detection_agent(state)
        assert result["fraud_check"]["fraud_score"] == 0
        assert result["fraud_check"]["requires_manual_review"] is False

    def test_same_day_claims_triggers_review(self):
        claim = _make_claim(
            claimed_amount=4800,
            treatment_date="2024-10-30",
            claims_history=[
                ClaimHistoryEntry(claim_id="CLM1", date="2024-10-30", amount=1200, provider="A"),
                ClaimHistoryEntry(claim_id="CLM2", date="2024-10-30", amount=1800, provider="B"),
                ClaimHistoryEntry(claim_id="CLM3", date="2024-10-30", amount=2100, provider="C"),
            ]
        )
        state = _initial_state(claim)
        result = fraud_detection_agent(state)
        assert result["fraud_check"]["requires_manual_review"] is True
        assert result["fraud_check"]["fraud_score"] > 0


# ── Full Pipeline Integration Tests ─────────────────────────────────────────

class TestFullPipeline:
    def test_clean_approval(self):
        """TC004: Clean consultation approved for ₹1,350."""
        claim = _make_claim(
            claimed_amount=1500,
            ytd_claims_amount=5000,
            documents=[
                DocumentUpload(
                    actual_type=DocumentType.PRESCRIPTION,
                    content=DocumentContent(
                        doctor_name="Dr. Arun Sharma",
                        patient_name="Rajesh Kumar",
                        diagnosis="Viral Fever",
                    )
                ),
                DocumentUpload(
                    actual_type=DocumentType.HOSPITAL_BILL,
                    content=DocumentContent(
                        patient_name="Rajesh Kumar",
                        total=1500,
                        line_items=[
                            {"description": "Consultation Fee", "amount": 1000},
                            {"description": "CBC Test", "amount": 300},
                            {"description": "Dengue NS1 Test", "amount": 200},
                        ]
                    )
                ),
            ]
        )
        result = process_claim(claim)
        assert result["decision"] == "APPROVED"
        assert result["approved_amount"] == 1350

    def test_wrong_documents_stops_early(self):
        """TC001: Wrong documents should stop before making a decision."""
        claim = _make_claim(documents=[
            DocumentUpload(file_name="prescription1.jpg", actual_type=DocumentType.PRESCRIPTION),
            DocumentUpload(file_name="prescription2.jpg", actual_type=DocumentType.PRESCRIPTION),
        ])
        result = process_claim(claim)
        # Should have doc verification failure info
        assert result.get("doc_verification") is not None
        assert result["doc_verification"]["passed"] is False

    def test_pipeline_doesnt_crash_on_component_failure(self):
        """TC011: Component failure should not crash the pipeline."""
        claim = _make_claim(
            claim_category=ClaimCategory.ALTERNATIVE_MEDICINE,
            claimed_amount=4000,
            simulate_component_failure=True,
            documents=[
                DocumentUpload(
                    actual_type=DocumentType.PRESCRIPTION,
                    content=DocumentContent(
                        doctor_name="Vaidya T. Krishnan",
                        diagnosis="Chronic Joint Pain",
                    )
                ),
                DocumentUpload(
                    actual_type=DocumentType.HOSPITAL_BILL,
                    content=DocumentContent(
                        hospital_name="Ayur Wellness Centre",
                        total=4000,
                    )
                ),
            ]
        )
        result = process_claim(claim)
        assert result["decision"] == "APPROVED"
        assert result["confidence_score"] < 0.95  # Degraded confidence
        assert len(result.get("component_failures", [])) > 0
