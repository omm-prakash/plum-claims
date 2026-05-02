"""
Agent 5: Fraud Detection Agent

Checks for fraud signals:
- Same-day claims exceeding limit
- Monthly claims exceeding limit
- High-value claims above threshold
- Computes fraud score and flags for manual review
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from models.claim import ClaimSubmission
from models.decision import FraudCheckResult, TraceStep, TraceStepStatus
from services.policy_engine import get_policy_engine
from agents.state import ClaimPipelineState


def fraud_detection_agent(state: ClaimPipelineState) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    engine = get_policy_engine()
    claim = ClaimSubmission(**state["claim"])
    thresholds = engine.get_fraud_thresholds()

    result = FraudCheckResult()
    checks: list[dict[str, Any]] = []

    # ── Check 1: Same-day claims ─────────────────────────────────────────
    same_day_claims = [h for h in claim.claims_history if h.date == claim.treatment_date]
    same_day_count = len(same_day_claims) + 1  # +1 for current claim
    limit = thresholds["same_day_claims_limit"]

    check1 = {"check": "Same-day claims", "status": "PASS", "detail": f"{same_day_count} claim(s) on {claim.treatment_date} (limit: {limit})"}
    if same_day_count > limit:
        check1["status"] = "FAIL"
        # Scale fraud score by how much the limit is exceeded
        excess_ratio = same_day_count / max(limit, 1)
        score_contribution = min(0.4 * excess_ratio, 0.9)
        result.fraud_score += score_contribution
        result.requires_manual_review = True  # Same-day breach always triggers manual review
        result.signals.append({
            "signal": "EXCESSIVE_SAME_DAY_CLAIMS",
            "detail": f"Member has {same_day_count} claims on {claim.treatment_date}, exceeding the limit of {limit}. "
                      f"This is {excess_ratio:.1f}x the allowed limit.",
            "previous_claims": [{"id": c.claim_id, "amount": c.amount, "provider": c.provider} for c in same_day_claims],
            "severity": "HIGH",
        })
        result.details.append(f"⚠️ {same_day_count} claims on the same day (limit: {limit})")
    checks.append(check1)

    # ── Check 2: Monthly claims ──────────────────────────────────────────
    treatment_month = claim.treatment_date[:7]  # YYYY-MM
    monthly_claims = [h for h in claim.claims_history if h.date.startswith(treatment_month)]
    monthly_count = len(monthly_claims) + 1
    monthly_limit = thresholds["monthly_claims_limit"]

    check2 = {"check": "Monthly claims", "status": "PASS", "detail": f"{monthly_count} claim(s) in {treatment_month} (limit: {monthly_limit})"}
    if monthly_count > monthly_limit:
        check2["status"] = "FAIL"
        result.fraud_score += 0.3
        result.signals.append({"signal": "EXCESSIVE_MONTHLY_CLAIMS", "detail": f"{monthly_count} claims in {treatment_month}, exceeding limit of {monthly_limit}.", "severity": "MEDIUM"})
        result.details.append(f"⚠️ {monthly_count} claims this month (limit: {monthly_limit})")
    checks.append(check2)

    # ── Check 3: High-value claim ────────────────────────────────────────
    hv_threshold = thresholds["high_value_claim_threshold"]
    check3 = {"check": "High-value claim", "status": "PASS", "detail": f"₹{claim.claimed_amount:,.0f} (threshold: ₹{hv_threshold:,.0f})"}
    if claim.claimed_amount > hv_threshold:
        check3["status"] = "FAIL"
        result.fraud_score += 0.2
        result.signals.append({"signal": "HIGH_VALUE_CLAIM", "detail": f"Claimed amount ₹{claim.claimed_amount:,.0f} exceeds high-value threshold ₹{hv_threshold:,.0f}.", "severity": "MEDIUM"})
        result.details.append(f"⚠️ High-value claim: ₹{claim.claimed_amount:,.0f}")
    checks.append(check3)

    # ── Determine if manual review required ──────────────────────────────
    fraud_threshold = thresholds["fraud_score_manual_review_threshold"]
    result.fraud_score = min(result.fraud_score, 1.0)
    if result.fraud_score >= fraud_threshold or claim.claimed_amount > thresholds["auto_manual_review_above"]:
        result.requires_manual_review = True
        result.details.append(f"🚨 Fraud score {result.fraud_score:.2f} exceeds threshold {fraud_threshold}. Routing to manual review.")

    completed_at = datetime.now(timezone.utc)
    trace_step = TraceStep(
        agent_name="fraud_detector", display_name="🚨 Fraud Detection",
        status=TraceStepStatus.WARNING if result.requires_manual_review else TraceStepStatus.SUCCESS,
        started_at=started_at, completed_at=completed_at,
        duration_ms=(completed_at - started_at).total_seconds() * 1000,
        input_summary={"claimed_amount": claim.claimed_amount, "history_count": len(claim.claims_history)},
        output_summary={"fraud_score": result.fraud_score, "signals_count": len(result.signals), "manual_review": result.requires_manual_review},
        checks_performed=checks,
        warnings=[d for d in result.details if "⚠️" in d or "🚨" in d],
        message=f"Fraud score: {result.fraud_score:.2f}. {'Manual review required.' if result.requires_manual_review else 'No fraud signals detected.'}",
    )

    return {
        "fraud_check": result.model_dump(),
        "trace": state.get("trace", []) + [trace_step.model_dump()],
    }
