"""
Policy Engine — loads policy_terms.json and provides methods to query
coverage rules, waiting periods, exclusions, and member data.

This is the single source of truth for all policy logic.
No policy rules are hardcoded anywhere else in the system.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

from models.policy import (
    DocumentRequirement,
    Member,
    OPDCategory,
    PolicyTerms,
)
from config import POLICY_TERMS_PATH


class PolicyEngine:
    """
    Stateless policy query engine. Loads the policy configuration once
    and provides typed accessor methods for all rules.
    """

    def __init__(self, policy_path: str | None = None):
        path = policy_path or str(POLICY_TERMS_PATH)
        with open(path, "r") as f:
            raw = json.load(f)
        self.policy = PolicyTerms(**raw)
        # Build lookup indexes
        self._members_by_id: dict[str, Member] = {
            m.member_id: m for m in self.policy.members
        }

    # ── Member Lookup ────────────────────────────────────────────────────

    def get_member(self, member_id: str) -> Member | None:
        return self._members_by_id.get(member_id)

    def get_primary_member(self, member_id: str) -> Member | None:
        """Get the primary member (self or the employee for a dependent)."""
        member = self.get_member(member_id)
        if member is None:
            return None
        if member.primary_member_id:
            return self.get_member(member.primary_member_id)
        return member

    # ── Document Requirements ────────────────────────────────────────────

    def get_document_requirements(self, category: str) -> DocumentRequirement | None:
        return self.policy.document_requirements.get(category)

    # ── Coverage & Limits ────────────────────────────────────────────────

    def get_category_config(self, category: str) -> OPDCategory | None:
        key = category.lower()
        return self.policy.opd_categories.get(key)

    def get_sub_limit(self, category: str) -> float:
        cat = self.get_category_config(category)
        return cat.sub_limit if cat else 0

    def get_copay_percent(self, category: str) -> float:
        cat = self.get_category_config(category)
        return cat.copay_percent if cat else 0

    def get_network_discount_percent(self, category: str) -> float:
        cat = self.get_category_config(category)
        return cat.network_discount_percent if cat else 0

    def get_per_claim_limit(self) -> float:
        return self.policy.coverage.per_claim_limit

    def get_annual_opd_limit(self) -> float:
        return self.policy.coverage.annual_opd_limit

    # ── Network Hospital Check ───────────────────────────────────────────

    def is_network_hospital(self, hospital_name: str | None) -> bool:
        if not hospital_name:
            return False
        name_lower = hospital_name.lower()
        for nh in self.policy.network_hospitals:
            if nh.lower() in name_lower or name_lower in nh.lower():
                return True
        return False

    # ── Waiting Period Check ─────────────────────────────────────────────

    def check_waiting_period(
        self,
        member: Member,
        diagnosis: str | None,
        treatment_date: str,
    ) -> dict[str, Any]:
        """
        Check if the member is still within a waiting period for the given diagnosis.
        Returns:
            {
                "eligible": True/False,
                "reason": str,
                "eligible_from": str (date) if not eligible
            }
        """
        join_date = self._parse_date(member.join_date or "2024-04-01")
        treat_date = self._parse_date(treatment_date)

        # 1. Initial waiting period (30 days)
        initial_end = join_date + timedelta(
            days=self.policy.waiting_periods.initial_waiting_period_days
        )
        if treat_date < initial_end:
            return {
                "eligible": False,
                "reason": f"Initial waiting period of {self.policy.waiting_periods.initial_waiting_period_days} days has not elapsed. "
                          f"Member joined on {member.join_date}.",
                "eligible_from": initial_end.isoformat(),
                "violation_code": "WAITING_PERIOD",
            }

        # 2. Condition-specific waiting periods
        if diagnosis:
            diag_lower = diagnosis.lower()
            for condition, days in self.policy.waiting_periods.specific_conditions.items():
                condition_keywords = self._get_condition_keywords(condition)
                if any(kw in diag_lower for kw in condition_keywords):
                    condition_end = join_date + timedelta(days=days)
                    if treat_date < condition_end:
                        return {
                            "eligible": False,
                            "reason": f"Waiting period of {days} days for {condition.replace('_', ' ').title()} "
                                      f"has not elapsed. Member joined on {member.join_date}. "
                                      f"Eligible from {condition_end.isoformat()}.",
                            "eligible_from": condition_end.isoformat(),
                            "violation_code": "WAITING_PERIOD",
                        }

        return {"eligible": True, "reason": "No waiting period applies"}

    # ── Exclusion Check ──────────────────────────────────────────────────

    def check_exclusions(
        self,
        diagnosis: str | None,
        treatment: str | None,
        category: str | None = None,
        line_items: list[dict] | None = None,
    ) -> dict[str, Any]:
        """
        Check if the diagnosis/treatment is excluded under the policy.
        Returns:
            {
                "excluded": True/False,
                "reasons": [str],
                "excluded_items": [str]  (specific line items that are excluded)
            }
        """
        excluded_reasons: list[str] = []
        excluded_items: list[str] = []
        combined_text = f"{diagnosis or ''} {treatment or ''}".lower()

        # General exclusions
        for excl in self.policy.exclusions.conditions:
            excl_keywords = self._get_exclusion_keywords(excl)
            if any(kw in combined_text for kw in excl_keywords):
                excluded_reasons.append(
                    f"'{excl}' is explicitly excluded under the policy."
                )

        # Category-specific exclusions
        if category:
            cat_config = self.get_category_config(category)
            if cat_config:
                # Dental exclusions
                if category == "DENTAL" and cat_config.excluded_procedures:
                    if line_items:
                        for item in line_items:
                            desc = item.get("description", "").lower()
                            for excl_proc in cat_config.excluded_procedures:
                                if excl_proc.lower() in desc or desc in excl_proc.lower():
                                    excluded_items.append(item.get("description", ""))
                    # Also check diagnosis/treatment text
                    for excl_proc in cat_config.excluded_procedures:
                        if excl_proc.lower() in combined_text:
                            excluded_reasons.append(
                                f"'{excl_proc}' is an excluded dental procedure."
                            )

                # Vision exclusions
                if category == "VISION" and cat_config.excluded_items:
                    for excl_item in cat_config.excluded_items:
                        if excl_item.lower() in combined_text:
                            excluded_reasons.append(
                                f"'{excl_item}' is excluded under vision coverage."
                            )

        # Dental exclusions from general list
        if category == "DENTAL":
            for excl in self.policy.exclusions.dental_exclusions:
                if excl.lower() in combined_text:
                    excluded_reasons.append(
                        f"'{excl}' is excluded under dental coverage."
                    )

        # Add reasons for each excluded line item (if not already covered by a general reason)
        for item_desc in excluded_items:
            reason = f"'{item_desc}' is an excluded procedure under {category} coverage."
            if reason not in excluded_reasons:
                excluded_reasons.append(reason)

        has_exclusions = len(excluded_reasons) > 0 or len(excluded_items) > 0
        return {
            "excluded": has_exclusions,
            "reasons": excluded_reasons,
            "excluded_items": excluded_items,
            "violation_code": "EXCLUDED_CONDITION" if has_exclusions else None,
        }

    # ── Pre-Authorization Check ──────────────────────────────────────────

    def check_pre_auth_required(
        self,
        category: str,
        line_items: list[dict] | None,
        claimed_amount: float,
    ) -> dict[str, Any]:
        """
        Check if pre-authorization is required for this claim.
        Returns:
            {
                "required": True/False,
                "reason": str
            }
        """
        cat_config = self.get_category_config(category)
        if not cat_config:
            return {"required": False, "reason": "Category not found"}

        # Check high-value tests
        if cat_config.high_value_tests_requiring_pre_auth and line_items:
            for item in line_items:
                desc = (item.get("description", "") or "").lower()
                for test in cat_config.high_value_tests_requiring_pre_auth:
                    if test.lower() in desc:
                        threshold = cat_config.pre_auth_threshold or 0
                        if claimed_amount > threshold:
                            return {
                                "required": True,
                                "reason": f"Pre-authorization is required for {test} "
                                          f"when the amount exceeds ₹{threshold:,.0f}. "
                                          f"Your claim amount is ₹{claimed_amount:,.0f}. "
                                          f"Please obtain pre-authorization and resubmit.",
                                "violation_code": "PRE_AUTH_MISSING",
                            }

        # Check general pre-auth rules
        for rule in self.policy.pre_authorization.required_for:
            rule_lower = rule.lower()
            if line_items:
                for item in line_items:
                    desc = (item.get("description", "") or "").lower()
                    # Match "MRI scan" or "CT scan" in the rule
                    test_name_match = re.match(r"(\w+\s*\w*)\s*scan", rule_lower)
                    if test_name_match:
                        test_name = test_name_match.group(1).strip()
                        if test_name in desc:
                            # Check if there's an amount threshold in the rule
                            amount_match = re.search(r"₹([\d,]+)", rule)
                            if amount_match:
                                threshold = float(amount_match.group(1).replace(",", ""))
                                if claimed_amount > threshold:
                                    return {
                                        "required": True,
                                        "reason": f"Pre-authorization is required for {rule}. "
                                                  f"Your claim amount is ₹{claimed_amount:,.0f}. "
                                                  f"Please obtain pre-authorization and resubmit.",
                                        "violation_code": "PRE_AUTH_MISSING",
                                    }

        return {"required": False, "reason": "Pre-authorization not required"}

    # ── Per-Claim Limit Check ────────────────────────────────────────────

    def check_per_claim_limit(self, claimed_amount: float) -> dict[str, Any]:
        limit = self.get_per_claim_limit()
        if claimed_amount > limit:
            return {
                "exceeded": True,
                "reason": f"Claimed amount ₹{claimed_amount:,.0f} exceeds the per-claim limit of ₹{limit:,.0f}.",
                "limit": limit,
                "violation_code": "PER_CLAIM_EXCEEDED",
            }
        return {"exceeded": False, "reason": "Within per-claim limit", "limit": limit}

    # ── Fraud Thresholds ─────────────────────────────────────────────────

    def get_fraud_thresholds(self) -> dict[str, Any]:
        ft = self.policy.fraud_thresholds
        return {
            "same_day_claims_limit": ft.same_day_claims_limit,
            "monthly_claims_limit": ft.monthly_claims_limit,
            "high_value_claim_threshold": ft.high_value_claim_threshold,
            "auto_manual_review_above": ft.auto_manual_review_above,
            "fraud_score_manual_review_threshold": ft.fraud_score_manual_review_threshold,
        }

    # ── Minimum Claim Amount ─────────────────────────────────────────────

    def get_minimum_claim_amount(self) -> float:
        return self.policy.submission_rules.minimum_claim_amount

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _parse_date(date_str: str) -> date:
        """Parse a date string in YYYY-MM-DD format."""
        return datetime.strptime(date_str, "%Y-%m-%d").date()

    @staticmethod
    def _get_condition_keywords(condition: str) -> list[str]:
        """Map condition keys from policy to diagnosis keywords."""
        mapping = {
            "diabetes": ["diabetes", "t2dm", "type 2 diabetes", "diabetic"],
            "hypertension": ["hypertension", "htn", "high blood pressure"],
            "thyroid_disorders": ["thyroid", "hypothyroid", "hyperthyroid"],
            "joint_replacement": ["joint replacement", "knee replacement", "hip replacement"],
            "maternity": ["maternity", "pregnancy", "prenatal", "postnatal"],
            "mental_health": ["mental health", "depression", "anxiety", "psychiatric"],
            "obesity_treatment": ["obesity", "bariatric", "weight loss", "bmi"],
            "hernia": ["hernia"],
            "cataract": ["cataract"],
        }
        return mapping.get(condition, [condition.replace("_", " ")])

    @staticmethod
    def _get_exclusion_keywords(exclusion: str) -> list[str]:
        """Map exclusion text to matching keywords."""
        text = exclusion.lower()
        keywords = [text]
        # Add specific keyword matches
        if "obesity" in text or "weight loss" in text:
            keywords.extend(["obesity", "bariatric", "weight loss", "bmi", "diet plan", "diet program"])
        if "cosmetic" in text:
            keywords.extend(["cosmetic", "aesthetic", "whitening", "bleaching"])
        if "self-inflicted" in text:
            keywords.extend(["self-inflicted", "self inflicted"])
        if "substance abuse" in text:
            keywords.extend(["substance abuse", "drug abuse", "alcohol abuse"])
        if "experimental" in text:
            keywords.extend(["experimental", "clinical trial"])
        if "infertility" in text:
            keywords.extend(["infertility", "ivf", "fertility"])
        if "bariatric" in text:
            keywords.extend(["bariatric", "obesity", "weight loss"])
        return keywords


# ── Singleton ────────────────────────────────────────────────────────────────

_engine_instance: PolicyEngine | None = None


def get_policy_engine() -> PolicyEngine:
    """Get or create the singleton policy engine instance."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = PolicyEngine()
    return _engine_instance
