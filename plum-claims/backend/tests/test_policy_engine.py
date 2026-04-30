"""
Unit tests for the PolicyEngine service.
Tests all policy query methods against the provided policy_terms.json.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.policy_engine import PolicyEngine
from models.policy import Member


@pytest.fixture
def engine():
    return PolicyEngine()


class TestMemberLookup:
    def test_get_existing_member(self, engine):
        member = engine.get_member("EMP001")
        assert member is not None
        assert member.name == "Rajesh Kumar"
        assert member.member_id == "EMP001"

    def test_get_nonexistent_member(self, engine):
        assert engine.get_member("EMP999") is None

    def test_get_dependent(self, engine):
        dep = engine.get_member("DEP001")
        assert dep is not None
        assert dep.name == "Sunita Kumar"
        assert dep.relationship == "SPOUSE"

    def test_get_primary_member_for_dependent(self, engine):
        primary = engine.get_primary_member("DEP001")
        assert primary is not None
        assert primary.member_id == "EMP001"

    def test_get_primary_member_for_self(self, engine):
        primary = engine.get_primary_member("EMP001")
        assert primary is not None
        assert primary.member_id == "EMP001"


class TestDocumentRequirements:
    def test_consultation_requires_prescription_and_bill(self, engine):
        reqs = engine.get_document_requirements("CONSULTATION")
        assert reqs is not None
        assert "PRESCRIPTION" in reqs.required
        assert "HOSPITAL_BILL" in reqs.required

    def test_pharmacy_requires_prescription_and_pharmacy_bill(self, engine):
        reqs = engine.get_document_requirements("PHARMACY")
        assert "PRESCRIPTION" in reqs.required
        assert "PHARMACY_BILL" in reqs.required

    def test_dental_requires_hospital_bill(self, engine):
        reqs = engine.get_document_requirements("DENTAL")
        assert "HOSPITAL_BILL" in reqs.required

    def test_unknown_category_returns_none(self, engine):
        assert engine.get_document_requirements("UNKNOWN") is None


class TestCoverageLimits:
    def test_per_claim_limit(self, engine):
        assert engine.get_per_claim_limit() == 5000

    def test_annual_opd_limit(self, engine):
        assert engine.get_annual_opd_limit() == 50000

    def test_minimum_claim_amount(self, engine):
        assert engine.get_minimum_claim_amount() == 500

    def test_consultation_copay(self, engine):
        assert engine.get_copay_percent("CONSULTATION") == 10

    def test_diagnostic_copay(self, engine):
        assert engine.get_copay_percent("DIAGNOSTIC") == 0

    def test_consultation_sub_limit(self, engine):
        assert engine.get_sub_limit("CONSULTATION") == 2000

    def test_dental_sub_limit(self, engine):
        assert engine.get_sub_limit("DENTAL") == 10000

    def test_network_discount_consultation(self, engine):
        assert engine.get_network_discount_percent("CONSULTATION") == 20


class TestNetworkHospitals:
    def test_apollo_is_network(self, engine):
        assert engine.is_network_hospital("Apollo Hospitals") is True

    def test_partial_match(self, engine):
        assert engine.is_network_hospital("Apollo") is True

    def test_random_hospital_not_network(self, engine):
        assert engine.is_network_hospital("Random Clinic") is False

    def test_none_hospital(self, engine):
        assert engine.is_network_hospital(None) is False


class TestWaitingPeriod:
    def test_within_initial_waiting_period(self, engine):
        member = Member(member_id="TEST", name="Test", date_of_birth="1990-01-01",
                       gender="M", relationship="SELF", join_date="2024-09-01")
        result = engine.check_waiting_period(member, "Viral Fever", "2024-09-15")
        assert result["eligible"] is False
        assert "WAITING_PERIOD" in result.get("violation_code", "")

    def test_past_initial_waiting_period(self, engine):
        member = Member(member_id="TEST", name="Test", date_of_birth="1990-01-01",
                       gender="M", relationship="SELF", join_date="2024-04-01")
        result = engine.check_waiting_period(member, "Viral Fever", "2024-11-01")
        assert result["eligible"] is True

    def test_diabetes_specific_waiting_period(self, engine):
        member = engine.get_member("EMP005")  # Joined 2024-09-01
        result = engine.check_waiting_period(member, "Type 2 Diabetes Mellitus", "2024-10-15")
        assert result["eligible"] is False
        assert "WAITING_PERIOD" in result["violation_code"]

    def test_diabetes_after_waiting_period(self, engine):
        member = engine.get_member("EMP005")  # Joined 2024-09-01
        result = engine.check_waiting_period(member, "Type 2 Diabetes", "2025-02-01")
        assert result["eligible"] is True


class TestExclusions:
    def test_obesity_excluded(self, engine):
        result = engine.check_exclusions("Morbid Obesity — BMI 37",
                                          "Bariatric Consultation", "CONSULTATION")
        assert result["excluded"] is True
        assert result["violation_code"] == "EXCLUDED_CONDITION"

    def test_teeth_whitening_excluded(self, engine):
        line_items = [
            {"description": "Root Canal Treatment", "amount": 8000},
            {"description": "Teeth Whitening", "amount": 4000}
        ]
        result = engine.check_exclusions(None, None, "DENTAL", line_items)
        assert result["excluded"] is True
        assert "Teeth Whitening" in result["excluded_items"]

    def test_viral_fever_not_excluded(self, engine):
        result = engine.check_exclusions("Viral Fever", None, "CONSULTATION")
        assert result["excluded"] is False

    def test_cosmetic_excluded(self, engine):
        result = engine.check_exclusions("Cosmetic surgery", "Aesthetic procedure")
        assert result["excluded"] is True


class TestPreAuthorization:
    def test_mri_above_threshold_requires_preauth(self, engine):
        line_items = [{"description": "MRI Lumbar Spine", "amount": 15000}]
        result = engine.check_pre_auth_required("DIAGNOSTIC", line_items, 15000)
        assert result["required"] is True
        assert "PRE_AUTH_MISSING" in result["violation_code"]

    def test_mri_below_threshold_no_preauth(self, engine):
        line_items = [{"description": "MRI Scan", "amount": 8000}]
        result = engine.check_pre_auth_required("DIAGNOSTIC", line_items, 8000)
        assert result["required"] is False

    def test_consultation_no_preauth(self, engine):
        result = engine.check_pre_auth_required("CONSULTATION", None, 1500)
        assert result["required"] is False


class TestPerClaimLimit:
    def test_within_limit(self, engine):
        result = engine.check_per_claim_limit(4000)
        assert result["exceeded"] is False

    def test_exceeds_limit(self, engine):
        result = engine.check_per_claim_limit(7500)
        assert result["exceeded"] is True
        assert result["violation_code"] == "PER_CLAIM_EXCEEDED"

    def test_at_limit(self, engine):
        result = engine.check_per_claim_limit(5000)
        assert result["exceeded"] is False


class TestFraudThresholds:
    def test_thresholds_loaded(self, engine):
        thresholds = engine.get_fraud_thresholds()
        assert thresholds["same_day_claims_limit"] == 2
        assert thresholds["monthly_claims_limit"] == 6
        assert thresholds["high_value_claim_threshold"] == 25000
        assert thresholds["fraud_score_manual_review_threshold"] == 0.80
