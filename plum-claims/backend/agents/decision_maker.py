"""
Agent 6: Decision Maker Agent

Aggregates outputs from all previous agents and produces the final
claim decision: APPROVED, PARTIAL, REJECTED, or MANUAL_REVIEW.

Also computes a confidence score and generates a human-readable explanation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from models.claim import ClaimSubmission
from models.decision import (
    AmountBreakdown, ClaimDecision, DecisionResult,
    DocVerificationResult, FraudCheckResult, PolicyCheckResult,
    TraceStep, TraceStepStatus,
)
from agents.state import ClaimPipelineState
from services.llm_service import evaluate_decision_confidence


def decision_maker_agent(state: ClaimPipelineState) -> dict[str, Any]:
    started_at = datetime.utcnow()
    claim = ClaimSubmission(**state["claim"])
    doc_verification = state.get("doc_verification", {})
    policy_check = state.get("policy_check", {})
    amount_calc = state.get("amount_calc", {})
    fraud_check = state.get("fraud_check", {})
    component_failures = state.get("component_failures", [])

    decision = ClaimDecision.APPROVED
    reasons: list[str] = []
    confidence = 0.95
    explanation_parts: list[str] = []

    # ── 1. Document verification failed → no decision ────────────────────
    if not doc_verification.get("passed", True):
        error_msg = doc_verification.get("error_message", "Document verification failed.")
        result = DecisionResult(
            claim_id=claim.claim_id, decision=ClaimDecision.REJECTED,
            approved_amount=0, claimed_amount=claim.claimed_amount,
            confidence_score=0.99, reasons=["DOCUMENT_VERIFICATION_FAILED"],
            explanation=error_msg,
            doc_verification=DocVerificationResult(**doc_verification) if doc_verification else None,
            trace=state.get("trace", []),
            component_failures=component_failures,
        )
        return _build_output(state, result, started_at)
    # ── 1.5. Extraction failed (critical info missing) → MANUAL_REVIEW ───
    if state.get("should_stop", False) and doc_verification.get("passed", True):
        result = DecisionResult(
            claim_id=claim.claim_id, decision=ClaimDecision.MANUAL_REVIEW,
            approved_amount=0, claimed_amount=claim.claimed_amount,
            confidence_score=0.1, reasons=["EXTRACTION_FAILED"],
            explanation="Critical information (Diagnosis) could not be extracted from the documents. Routing to manual review.",
            trace=state.get("trace", []),
            component_failures=component_failures + ["document_extractor"],
        )
        return _build_output(state, result, started_at)

    # ── 2. Policy violations → REJECTED ──────────────────────────────────
    violations = policy_check.get("violations", [])
    if violations:
        # Check if it's a partial rejection (some items excluded but others approved)
        excluded_items = []
        hard_rejections = []
        for v in violations:
            code = v.get("code", "")
            if code == "EXCLUDED_CONDITION" and v.get("excluded_items"):
                excluded_items.extend(v["excluded_items"])
            else:
                hard_rejections.append(v)

        approved_amount = amount_calc.get("final_approved_amount", 0)

        if hard_rejections:
            decision = ClaimDecision.REJECTED
            reasons = [v.get("code", "POLICY_VIOLATION") for v in hard_rejections]
            explanation_parts.append("Claim rejected due to policy violations:")
            for v in hard_rejections:
                explanation_parts.append(f"• {v.get('message', 'Policy violation')}")
            confidence = 0.95
        elif excluded_items and approved_amount > 0:
            decision = ClaimDecision.PARTIAL
            reasons = ["PARTIAL_EXCLUSION"]
            explanation_parts.append(f"Claim partially approved for ₹{approved_amount:,.0f}.")
            explanation_parts.append(f"The following items were excluded: {', '.join(excluded_items)}.")
            confidence = 0.90
        elif excluded_items and approved_amount == 0:
            decision = ClaimDecision.REJECTED
            reasons = ["EXCLUDED_CONDITION"]
            explanation_parts.append("All claimed items are excluded under the policy.")
            confidence = 0.95
    else:
        explanation_parts.append("All policy checks passed.")

    # ── Calculate Context for Confidence Scoring ─────────────────────────
    extracted_data = state.get("extracted_data", [])
    avg_extraction_conf = 1.0
    if extracted_data:
        avg_extraction_conf = sum(e.get("extraction_confidence", 1.0) for e in extracted_data) / len(extracted_data)
        
    fraud_score = fraud_check.get("fraud_score", 0.0)

    # ── 3. Fraud signals → MANUAL_REVIEW ─────────────────────────────────
    if fraud_check.get("requires_manual_review", False):
        decision = ClaimDecision.MANUAL_REVIEW
        if "FRAUD_SIGNALS_DETECTED" not in reasons:
            reasons.append("FRAUD_SIGNALS_DETECTED")
        fraud_signals = fraud_check.get("signals", [])
        explanation_parts.append("Claim flagged for manual review due to suspicious patterns:")
        for sig in fraud_signals:
            explanation_parts.append(f"• {sig.get('signal', '')}: {sig.get('detail', '')}")

    # ── 3.5. Low Extraction Confidence → MANUAL_REVIEW ───────────────────
    if avg_extraction_conf < 0.80:
        if decision != ClaimDecision.REJECTED:
            decision = ClaimDecision.MANUAL_REVIEW
        if "LOW_EXTRACTION_CONFIDENCE" not in reasons:
            reasons.append("LOW_EXTRACTION_CONFIDENCE")
        explanation_parts.append(f"Claim flagged for manual review due to low AI extraction confidence ({avg_extraction_conf:.0%}).")

    # ── 4. Component failures ────────────────────────────────────────────
    if component_failures:
        explanation_parts.append(f"⚠️ Component failure(s) detected: {', '.join(component_failures)}. Confidence reduced. Manual review recommended.")

    # ── 4.5 Evaluate Final Confidence using LLM ──────────────────────────
    confidence = evaluate_decision_confidence(
        decision=decision.value,
        reasons=reasons,
        avg_extraction_conf=avg_extraction_conf,
        fraud_score=fraud_score,
        component_failures=component_failures
    )

    # ── 5. Compute final approved amount ─────────────────────────────────
    approved_amount = 0
    if decision in (ClaimDecision.APPROVED, ClaimDecision.PARTIAL):
        approved_amount = amount_calc.get("final_approved_amount", 0)
    elif decision == ClaimDecision.MANUAL_REVIEW:
        approved_amount = amount_calc.get("final_approved_amount", 0)  # Tentative

    # ── 6. Build explanation ─────────────────────────────────────────────
    if decision == ClaimDecision.APPROVED:
        explanation_parts.insert(0, f"Claim approved for ₹{approved_amount:,.0f} (claimed: ₹{claim.claimed_amount:,.0f}).")
        calc_steps = amount_calc.get("calculation_steps", [])
        if calc_steps:
            explanation_parts.append("Calculation breakdown:")
            for step in calc_steps:
                explanation_parts.append(f"  {step}")

    explanation = "\n".join(explanation_parts)

    # Build manual review note if needed
    manual_note = None
    if component_failures:
        manual_note = f"Manual review recommended due to component failure(s): {', '.join(component_failures)}. Processing completed with reduced confidence."

    result = DecisionResult(
        claim_id=claim.claim_id, decision=decision,
        approved_amount=round(approved_amount, 2),
        claimed_amount=claim.claimed_amount,
        confidence_score=round(confidence, 2),
        reasons=reasons, explanation=explanation,
        amount_breakdown=AmountBreakdown(**amount_calc) if amount_calc else None,
        doc_verification=DocVerificationResult(**doc_verification) if doc_verification else None,
        policy_check=PolicyCheckResult(**policy_check) if policy_check else None,
        fraud_check=FraudCheckResult(**fraud_check) if fraud_check else None,
        trace=state.get("trace", []),
        component_failures=component_failures,
        requires_manual_review_note=manual_note,
    )

    return _build_output(state, result, started_at)


def _build_output(state, result, started_at):
    completed_at = datetime.utcnow()
    trace_step = TraceStep(
        agent_name="decision_maker", display_name="⚖️ Final Decision",
        status=TraceStepStatus.SUCCESS,
        started_at=started_at, completed_at=completed_at,
        duration_ms=(completed_at - started_at).total_seconds() * 1000,
        input_summary={"agents_completed": len(state.get("trace", []))},
        output_summary={"decision": result.decision.value, "approved_amount": result.approved_amount, "confidence": result.confidence_score},
        message=f"Decision: {result.decision.value} | Amount: ₹{result.approved_amount:,.0f} | Confidence: {result.confidence_score:.0%}",
    )
    result.trace = state.get("trace", []) + [trace_step.model_dump()]

    return {"decision": result.model_dump()}
