"""
Agent 3: Policy Validation Agent

Checks claim eligibility against policy rules:
- Waiting periods (initial + condition-specific)
- Exclusions (general + category-specific)
- Pre-authorization requirements
- Per-claim limits
- Coverage verification
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from models.claim import ClaimSubmission
from models.decision import PolicyCheckResult, TraceStep, TraceStepStatus
from services.policy_engine import get_policy_engine
from agents.state import ClaimPipelineState


def policy_validation_agent(state: ClaimPipelineState) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    engine = get_policy_engine()
    claim = ClaimSubmission(**state["claim"])
    diagnosis = state.get("diagnosis")
    treatment = state.get("treatment")
    line_items = state.get("line_items")

    result = PolicyCheckResult(eligible=True)
    checks: list[dict[str, Any]] = []

    # ── Check 1: Member exists ───────────────────────────────────────────
    member = engine.get_member(claim.member_id)
    check1 = {"check": "Member verification", "status": "PASS", "detail": ""}
    if not member:
        check1["status"] = "FAIL"
        check1["detail"] = f"Member {claim.member_id} not found"
        result.eligible = False
        result.violations.append({"code": "MEMBER_NOT_FOUND", "message": f"Member {claim.member_id} not found in policy."})
    else:
        check1["detail"] = f"Member {member.name} ({member.member_id}) verified"
    checks.append(check1)
    result.checks_performed.append(check1)

    if not member:
        return _build_output(state, result, checks, started_at)

    # ── Check 2: Per-claim limit ─────────────────────────────────────────
    # Use the category-specific sub-limit if it's higher than the generic per-claim limit
    cat_config = engine.get_category_config(claim.claim_category.value)
    effective_limit = engine.get_per_claim_limit()
    if cat_config and cat_config.sub_limit > effective_limit:
        effective_limit = cat_config.sub_limit

    limit_check = engine.check_per_claim_limit(claim.claimed_amount)
    # When line items are present and category has excluded procedures/items,
    # the eligible amount may be lower after filtering. Don't hard-reject here;
    # let the amount calculator handle line-item-level filtering.
    has_excludable_items = (cat_config and (cat_config.excluded_procedures or cat_config.excluded_items)) and line_items
    if claim.claimed_amount <= effective_limit or has_excludable_items:
        detail = f"₹{claim.claimed_amount:,.0f} within effective limit ₹{effective_limit:,.0f}" if claim.claimed_amount <= effective_limit else f"₹{claim.claimed_amount:,.0f} exceeds limit but has line items subject to exclusion filtering"
        check2 = {"check": "Per-claim limit", "status": "PASS", "detail": detail}
    else:
        check2 = {"check": "Per-claim limit", "status": "FAIL" if limit_check["exceeded"] else "PASS", "detail": limit_check["reason"]}
        if limit_check["exceeded"]:
            result.eligible = False
            result.violations.append({"code": limit_check["violation_code"], "message": limit_check["reason"]})
    checks.append(check2)
    result.checks_performed.append(check2)

    # ── Check 3: Waiting period ──────────────────────────────────────────
    wp_check = engine.check_waiting_period(member, diagnosis, claim.treatment_date)
    check3 = {"check": "Waiting period", "status": "PASS" if wp_check["eligible"] else "FAIL", "detail": wp_check["reason"]}
    if not wp_check["eligible"]:
        result.eligible = False
        result.violations.append({"code": wp_check.get("violation_code", "WAITING_PERIOD"), "message": wp_check["reason"]})
    checks.append(check3)
    result.checks_performed.append(check3)

    # ── Check 4: Exclusions ──────────────────────────────────────────────
    excl_check = engine.check_exclusions(diagnosis, treatment, claim.claim_category.value, line_items)
    if excl_check["excluded"]:
        check4 = {"check": "Exclusion check", "status": "FAIL", "detail": "; ".join(excl_check["reasons"])}
        result.eligible = False
        result.violations.append({"code": excl_check.get("violation_code", "EXCLUDED_CONDITION"), "message": "; ".join(excl_check["reasons"]), "excluded_items": excl_check.get("excluded_items", [])})
    else:
        check4 = {"check": "Exclusion check", "status": "PASS", "detail": "No exclusions apply"}
    checks.append(check4)
    result.checks_performed.append(check4)

    # ── Check 5: Pre-authorization ───────────────────────────────────────
    preauth_check = engine.check_pre_auth_required(claim.claim_category.value, line_items, claim.claimed_amount)
    if preauth_check["required"]:
        check5 = {"check": "Pre-authorization", "status": "FAIL", "detail": preauth_check["reason"]}
        result.eligible = False
        result.violations.append({"code": preauth_check.get("violation_code", "PRE_AUTH_MISSING"), "message": preauth_check["reason"]})
    else:
        check5 = {"check": "Pre-authorization", "status": "PASS", "detail": "Not required or obtained"}
    checks.append(check5)
    result.checks_performed.append(check5)

    # ── Check 6: Category coverage ───────────────────────────────────────
    cat_config = engine.get_category_config(claim.claim_category.value)
    if cat_config and not cat_config.covered:
        check6 = {"check": "Category coverage", "status": "FAIL", "detail": f"{claim.claim_category.value} is not covered"}
        result.eligible = False
        result.violations.append({"code": "NOT_COVERED", "message": f"{claim.claim_category.value} is not covered under this policy."})
    else:
        check6 = {"check": "Category coverage", "status": "PASS", "detail": f"{claim.claim_category.value} is covered"}
    checks.append(check6)
    result.checks_performed.append(check6)

    # ── Check 7: Minimum claim amount ────────────────────────────────────
    min_amount = engine.get_minimum_claim_amount()
    if claim.claimed_amount < min_amount:
        check7 = {"check": "Minimum claim amount", "status": "FAIL", "detail": f"₹{claim.claimed_amount} is below minimum ₹{min_amount}"}
        result.eligible = False
        result.violations.append({"code": "BELOW_MINIMUM", "message": f"Claimed amount ₹{claim.claimed_amount} is below the minimum of ₹{min_amount}."})
    else:
        check7 = {"check": "Minimum claim amount", "status": "PASS", "detail": f"₹{claim.claimed_amount} meets minimum ₹{min_amount}"}
    checks.append(check7)
    result.checks_performed.append(check7)

    return _build_output(state, result, checks, started_at)


def _build_output(state, result, checks, started_at):
    completed_at = datetime.now(timezone.utc)
    has_violations = len(result.violations) > 0
    trace_step = TraceStep(
        agent_name="policy_validator", display_name="✅ Policy Validation",
        status=TraceStepStatus.FAILED if has_violations else TraceStepStatus.SUCCESS,
        started_at=started_at, completed_at=completed_at,
        duration_ms=(completed_at - started_at).total_seconds() * 1000,
        input_summary={"checks_count": len(checks)},
        output_summary={"eligible": result.eligible, "violations_count": len(result.violations), "violations": [v["code"] for v in result.violations]},
        checks_performed=checks,
        message=f"Policy check {'failed' if has_violations else 'passed'}: {len(result.violations)} violation(s) found." if has_violations else "All policy checks passed.",
    )
    return {
        "policy_check": result.model_dump(),
        "trace": state.get("trace", []) + [trace_step.model_dump()],
    }
