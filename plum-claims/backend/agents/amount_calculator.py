"""
Agent 4: Amount Calculation Agent

Applies financial rules in the correct order:
1. Filter out excluded line items
2. Apply sub-limits per category
3. Apply network hospital discount FIRST
4. Apply co-pay percentage on discounted amount
5. Apply per-claim cap
6. Apply annual OPD remaining cap
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from models.claim import ClaimSubmission
from models.decision import AmountBreakdown, LineItemDecision, TraceStep, TraceStepStatus
from services.policy_engine import get_policy_engine
from agents.state import ClaimPipelineState


def amount_calculation_agent(state: ClaimPipelineState) -> dict[str, Any]:
    started_at = datetime.now(timezone.utc)
    engine = get_policy_engine()
    claim = ClaimSubmission(**state["claim"])
    policy_check = state.get("policy_check", {})
    hospital_name = state.get("hospital_name") or claim.hospital_name
    line_items = state.get("line_items")
    category = claim.claim_category.value

    # If policy check found violations that are hard rejections, skip calculation
    violations = policy_check.get("violations", [])
    hard_reject_codes = {"WAITING_PERIOD", "PRE_AUTH_MISSING", "PER_CLAIM_EXCEEDED", "EXCLUDED_CONDITION", "NOT_COVERED", "MEMBER_NOT_FOUND"}
    has_hard_rejection = any(v.get("code") in hard_reject_codes for v in violations)

    # Get excluded items from policy check
    excluded_items_list: list[str] = []
    for v in violations:
        if v.get("excluded_items"):
            excluded_items_list.extend(v["excluded_items"])

    breakdown = AmountBreakdown(original_amount=claim.claimed_amount, eligible_amount=claim.claimed_amount)
    steps: list[str] = []

    if has_hard_rejection and not excluded_items_list:
        # Full rejection — no amount to calculate
        breakdown.final_approved_amount = 0
        steps.append(f"Claim rejected due to policy violation(s): {', '.join(v.get('code','') for v in violations)}")
        breakdown.calculation_steps = steps
        return _build_output(state, breakdown, started_at, steps)

    # ── Step 1: Filter line items ────────────────────────────────────────
    eligible_amount = claim.claimed_amount
    li_decisions: list[LineItemDecision] = []

    if line_items:
        approved_total = 0
        for item in line_items:
            desc = item.get("description", "")
            raw_amount = item.get("amount")
            amount = float(raw_amount) if raw_amount is not None else 0.0
            is_excluded = any(exc.lower() in desc.lower() or desc.lower() in exc.lower() for exc in excluded_items_list)

            # Also check dental/vision exclusions from policy
            cat_config = engine.get_category_config(category)
            if cat_config:
                for exc_proc in cat_config.excluded_procedures:
                    if exc_proc.lower() in desc.lower() or desc.lower() in exc_proc.lower():
                        is_excluded = True
                        if desc not in excluded_items_list:
                            excluded_items_list.append(desc)
                for exc_item in getattr(cat_config, 'excluded_items', []):
                    if exc_item.lower() in desc.lower() or desc.lower() in exc_item.lower():
                        is_excluded = True

            if is_excluded:
                li_decisions.append(LineItemDecision(description=desc, claimed_amount=amount, approved_amount=0, status="EXCLUDED", reason=f"'{desc}' is excluded under the policy"))
                steps.append(f"❌ Line item '{desc}' (₹{amount:,.0f}) — EXCLUDED")
            else:
                li_decisions.append(LineItemDecision(description=desc, claimed_amount=amount, approved_amount=amount, status="APPROVED"))
                approved_total += amount
                steps.append(f"✅ Line item '{desc}' (₹{amount:,.0f}) — APPROVED")

        eligible_amount = approved_total
        steps.append(f"Eligible amount after filtering: ₹{eligible_amount:,.0f}")
    else:
        steps.append(f"No line items provided. Using claimed amount: ₹{eligible_amount:,.0f}")

    breakdown.eligible_amount = eligible_amount
    breakdown.line_item_decisions = li_decisions

    # If all items were excluded
    if eligible_amount == 0:
        breakdown.final_approved_amount = 0
        breakdown.calculation_steps = steps
        return _build_output(state, breakdown, started_at, steps)

    # ── Step 2: Note sub-limit (informational, not capped here) ─────────
    sub_limit = engine.get_sub_limit(category)
    if sub_limit:
        breakdown.sub_limit_applied = sub_limit
        steps.append(f"Category sub-limit for {category}: ₹{sub_limit:,.0f} (annual)")

    current_amount = eligible_amount

    # ── Step 3: Network discount (applied FIRST, before co-pay) ──────────
    is_network = engine.is_network_hospital(hospital_name)
    discount_pct = engine.get_network_discount_percent(category) if is_network else 0

    if is_network and discount_pct > 0:
        discount_amount = current_amount * (discount_pct / 100)
        current_amount -= discount_amount
        breakdown.network_discount_applied = discount_amount
        breakdown.amount_after_discount = current_amount
        steps.append(f"🏥 Network hospital discount ({discount_pct}%): -₹{discount_amount:,.0f} → ₹{current_amount:,.0f}")
    else:
        breakdown.amount_after_discount = current_amount
        if hospital_name:
            steps.append(f"Hospital '{hospital_name}' is {'a network' if is_network else 'not a network'} hospital. No discount applied.")

    # ── Step 4: Co-pay (applied AFTER discount) ──────────────────────────
    copay_pct = engine.get_copay_percent(category)
    if copay_pct > 0:
        copay_amount = current_amount * (copay_pct / 100)
        current_amount -= copay_amount
        breakdown.copay_amount = copay_amount
        breakdown.amount_after_copay = current_amount
        steps.append(f"💳 Co-pay ({copay_pct}%): -₹{copay_amount:,.0f} → ₹{current_amount:,.0f}")
    else:
        breakdown.amount_after_copay = current_amount

    # ── Step 5: Per-claim limit (informational — rejection handled by policy validator)
    per_claim = engine.get_per_claim_limit()
    breakdown.per_claim_limit_applied = per_claim
    steps.append(f"Per-claim limit: ₹{per_claim:,.0f} (validated by policy check)")

    # ── Step 6: Annual OPD remaining ─────────────────────────────────────
    annual_limit = engine.get_annual_opd_limit()
    remaining = annual_limit - claim.ytd_claims_amount
    breakdown.annual_limit_remaining = remaining
    if current_amount > remaining:
        steps.append(f"Annual OPD remaining: ₹{remaining:,.0f}. Capping from ₹{current_amount:,.0f}")
        current_amount = max(0, remaining)

    breakdown.final_approved_amount = round(current_amount, 2)
    steps.append(f"✅ Final approved amount: ₹{breakdown.final_approved_amount:,.0f}")
    breakdown.calculation_steps = steps

    return _build_output(state, breakdown, started_at, steps)


def _build_output(state, breakdown, started_at, steps):
    completed_at = datetime.now(timezone.utc)
    trace_step = TraceStep(
        agent_name="amount_calculator", display_name="💰 Amount Calculation",
        status=TraceStepStatus.SUCCESS,
        started_at=started_at, completed_at=completed_at,
        duration_ms=(completed_at - started_at).total_seconds() * 1000,
        input_summary={"claimed_amount": breakdown.original_amount},
        output_summary={"approved_amount": breakdown.final_approved_amount, "steps_count": len(steps)},
        checks_performed=[{"step": s} for s in steps],
        message=f"Calculated approved amount: ₹{breakdown.final_approved_amount:,.0f}",
    )
    return {
        "amount_calc": breakdown.model_dump(),
        "trace": state.get("trace", []) + [trace_step.model_dump()],
    }
