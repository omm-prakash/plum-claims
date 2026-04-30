"""
Policy data models — mirrors the structure of policy_terms.json
so we can load and validate the policy configuration.
"""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class FamilyFloater(BaseModel):
    enabled: bool = False
    combined_limit: float = 0
    covered_relationships: list[str] = Field(default_factory=list)


class Coverage(BaseModel):
    sum_insured_per_employee: float
    annual_opd_limit: float
    per_claim_limit: float
    family_floater: FamilyFloater


class OPDCategory(BaseModel):
    sub_limit: float
    copay_percent: float = 0
    network_discount_percent: float = 0
    requires_prescription: bool = False
    requires_pre_auth: bool = False
    pre_auth_threshold: Optional[float] = None
    high_value_tests_requiring_pre_auth: list[str] = Field(default_factory=list)
    requires_dental_report: bool = False
    requires_registered_practitioner: bool = False
    max_sessions_per_year: Optional[int] = None
    branded_drug_copay_percent: Optional[float] = None
    generic_mandatory: bool = False
    covered: bool = True
    covered_procedures: list[str] = Field(default_factory=list)
    excluded_procedures: list[str] = Field(default_factory=list)
    covered_items: list[str] = Field(default_factory=list)
    excluded_items: list[str] = Field(default_factory=list)
    covered_systems: list[str] = Field(default_factory=list)


class WaitingPeriods(BaseModel):
    initial_waiting_period_days: int = 30
    pre_existing_conditions_days: int = 365
    specific_conditions: dict[str, int] = Field(default_factory=dict)


class Exclusions(BaseModel):
    conditions: list[str] = Field(default_factory=list)
    dental_exclusions: list[str] = Field(default_factory=list)
    vision_exclusions: list[str] = Field(default_factory=list)


class PreAuthorization(BaseModel):
    required_for: list[str] = Field(default_factory=list)
    validity_days: int = 30


class SubmissionRules(BaseModel):
    deadline_days_from_treatment: int = 30
    minimum_claim_amount: float = 500
    currency: str = "INR"


class FraudThresholds(BaseModel):
    same_day_claims_limit: int = 2
    monthly_claims_limit: int = 6
    high_value_claim_threshold: float = 25000
    auto_manual_review_above: float = 25000
    fraud_score_manual_review_threshold: float = 0.80


class PolicyHolder(BaseModel):
    company_name: str
    employee_count: int
    policy_start_date: str
    policy_end_date: str
    renewal_status: str


class Member(BaseModel):
    member_id: str
    name: str
    date_of_birth: str
    gender: str
    relationship: str
    join_date: Optional[str] = None
    primary_member_id: Optional[str] = None
    dependents: list[str] = Field(default_factory=list)


class DocumentRequirement(BaseModel):
    required: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)


class PolicyTerms(BaseModel):
    """Complete policy configuration loaded from policy_terms.json."""
    policy_id: str
    policy_name: str
    insurer: str
    policy_holder: PolicyHolder
    coverage: Coverage
    opd_categories: dict[str, OPDCategory]
    waiting_periods: WaitingPeriods
    exclusions: Exclusions
    pre_authorization: PreAuthorization
    network_hospitals: list[str] = Field(default_factory=list)
    submission_rules: SubmissionRules
    document_requirements: dict[str, DocumentRequirement]
    fraud_thresholds: FraudThresholds
    members: list[Member] = Field(default_factory=list)
