"""
LangGraph Pipeline — wires the 6 agents into a stateful graph with
conditional edges. The pipeline stops early if document verification fails.

Flow:
  document_verifier → [if pass] → document_extractor → policy_validator
  → amount_calculator → fraud_detector → decision_maker

  document_verifier → [if fail] → decision_maker (early stop with error)
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import StateGraph, END

from agents.state import ClaimPipelineState
from agents.document_verifier import document_verification_agent
from agents.document_extractor import document_extraction_agent
from agents.policy_validator import policy_validation_agent
from agents.amount_calculator import amount_calculation_agent
from agents.fraud_detector import fraud_detection_agent
from agents.decision_maker import decision_maker_agent
from models.claim import ClaimSubmission


def _should_continue_after_verification(state: ClaimPipelineState) -> str:
    """Route based on document verification result."""
    if state.get("should_stop", False):
        return "decision_maker"  # Skip to decision with error
    return "document_extractor"


def build_claims_pipeline() -> StateGraph:
    """Build and compile the claims processing LangGraph pipeline."""
    workflow = StateGraph(ClaimPipelineState)

    # Add nodes
    workflow.add_node("document_verifier", document_verification_agent)
    workflow.add_node("document_extractor", document_extraction_agent)
    workflow.add_node("policy_validator", policy_validation_agent)
    workflow.add_node("amount_calculator", amount_calculation_agent)
    workflow.add_node("fraud_detector", fraud_detection_agent)
    workflow.add_node("decision_maker", decision_maker_agent)

    # Set entry point
    workflow.set_entry_point("document_verifier")

    # Add conditional edge after verification
    workflow.add_conditional_edges(
        "document_verifier",
        _should_continue_after_verification,
        {
            "document_extractor": "document_extractor",
            "decision_maker": "decision_maker",
        }
    )

    # Linear flow for the rest
    workflow.add_edge("document_extractor", "policy_validator")
    workflow.add_edge("policy_validator", "amount_calculator")
    workflow.add_edge("amount_calculator", "fraud_detector")
    workflow.add_edge("fraud_detector", "decision_maker")
    workflow.add_edge("decision_maker", END)

    return workflow.compile()


# ── Pipeline Runner ──────────────────────────────────────────────────────────

_pipeline = None


def get_pipeline():
    """Get or create the singleton pipeline instance."""
    global _pipeline
    if _pipeline is None:
        _pipeline = build_claims_pipeline()
    return _pipeline


def process_claim(claim: ClaimSubmission) -> dict[str, Any]:
    """
    Run a claim through the full processing pipeline.
    
    Args:
        claim: The claim submission to process
        
    Returns:
        The final decision result as a dictionary
    """
    pipeline = get_pipeline()

    initial_state: ClaimPipelineState = {
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

    try:
        result = pipeline.invoke(initial_state)
        return result.get("decision", {"error": "No decision produced"})
    except Exception as e:
        # Graceful failure — return a decision even if the pipeline crashes
        from models.decision import ClaimDecision, DecisionResult, TraceStep, TraceStepStatus
        from datetime import datetime

        error_result = DecisionResult(
            claim_id=claim.claim_id,
            decision=ClaimDecision.MANUAL_REVIEW,
            approved_amount=0,
            claimed_amount=claim.claimed_amount,
            confidence_score=0.1,
            reasons=["PIPELINE_ERROR"],
            explanation=f"Pipeline encountered an error: {str(e)}. Routing to manual review.",
            component_failures=["pipeline"],
            requires_manual_review_note=f"Pipeline error: {str(e)}",
            trace=[TraceStep(
                agent_name="pipeline",
                display_name="⚠️ Pipeline Error",
                status=TraceStepStatus.FAILED,
                message=str(e),
            ).model_dump()],
        )
        return error_result.model_dump()
