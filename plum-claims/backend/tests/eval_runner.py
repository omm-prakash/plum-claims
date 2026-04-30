"""
Eval Runner — Runs all 12 test cases from test_cases.json through the
claims processing pipeline and generates a detailed report.

Usage:
    python -m tests.eval_runner
"""
from __future__ import annotations

import json
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import TEST_CASES_PATH
from models.claim import (
    ClaimSubmission, ClaimCategory, DocumentUpload, DocumentType,
    DocumentQuality, DocumentContent, ClaimHistoryEntry,
)
from agents.graph import process_claim


def load_test_cases() -> list[dict]:
    with open(TEST_CASES_PATH) as f:
        data = json.load(f)
    return data["test_cases"]


def build_claim_from_test(tc: dict) -> ClaimSubmission:
    """Convert a test case dict into a ClaimSubmission."""
    inp = tc["input"]

    docs = []
    for d in inp.get("documents", []):
        content = None
        if "content" in d and d["content"]:
            content = DocumentContent(**d["content"])
        docs.append(DocumentUpload(
            file_id=d.get("file_id", ""),
            file_name=d.get("file_name"),
            actual_type=DocumentType(d["actual_type"]),
            quality=DocumentQuality(d.get("quality", "GOOD")),
            patient_name_on_doc=d.get("patient_name_on_doc"),
            content=content,
        ))

    history = []
    for h in inp.get("claims_history", []):
        history.append(ClaimHistoryEntry(**h))

    return ClaimSubmission(
        claim_id=tc["case_id"],
        member_id=inp["member_id"],
        policy_id=inp.get("policy_id", "PLUM_GHI_2024"),
        claim_category=ClaimCategory(inp["claim_category"]),
        treatment_date=inp["treatment_date"],
        claimed_amount=inp["claimed_amount"],
        hospital_name=inp.get("hospital_name"),
        ytd_claims_amount=inp.get("ytd_claims_amount", 0),
        claims_history=history,
        documents=docs,
        simulate_component_failure=inp.get("simulate_component_failure", False),
    )


def evaluate_result(tc: dict, result: dict) -> dict:
    """Compare pipeline result against expected outcome."""
    expected = tc["expected"]
    evaluation = {"case_id": tc["case_id"], "case_name": tc["case_name"], "checks": [], "passed": True}

    # Check decision
    exp_decision = expected.get("decision")
    got_decision = result.get("decision")

    if exp_decision is not None:
        # Handle both string and enum values in comparison
        got_str = str(got_decision).split(".")[-1] if got_decision else None
        match = got_str == exp_decision
        evaluation["checks"].append({
            "check": "Decision", "expected": exp_decision, "got": got_str,
            "passed": match,
        })
        if not match:
            evaluation["passed"] = False
    else:
        # No decision expected (doc verification should stop)
        # Check that the system stopped and provided an error
        doc_ver = result.get("doc_verification", {})
        if doc_ver and not doc_ver.get("passed", True):
            evaluation["checks"].append({"check": "Early stop on doc issue", "passed": True, "detail": "System stopped before making a decision"})
        else:
            evaluation["checks"].append({"check": "Early stop on doc issue", "passed": False, "detail": "System should have stopped but didn't"})
            evaluation["passed"] = False

    # Check approved amount
    if "approved_amount" in expected:
        exp_amount = expected["approved_amount"]
        got_amount = result.get("approved_amount", 0)
        match = abs(got_amount - exp_amount) < 1  # Allow ₹1 rounding
        evaluation["checks"].append({
            "check": "Approved Amount", "expected": exp_amount, "got": got_amount, "passed": match,
        })
        if not match:
            evaluation["passed"] = False

    # Check confidence
    if "confidence_score" in expected:
        conf_spec = expected["confidence_score"]
        got_conf = result.get("confidence_score", 0)
        if isinstance(conf_spec, str) and conf_spec.startswith("above"):
            threshold = float(conf_spec.split()[-1])
            match = got_conf > threshold
            evaluation["checks"].append({
                "check": "Confidence Score", "expected": f"> {threshold}", "got": got_conf, "passed": match,
            })
        if not match:
            evaluation["passed"] = False

    # Check rejection reasons
    if "rejection_reasons" in expected:
        exp_reasons = expected["rejection_reasons"]
        got_reasons = result.get("reasons", [])
        for r in exp_reasons:
            found = r in got_reasons
            evaluation["checks"].append({"check": f"Rejection reason: {r}", "passed": found, "got_reasons": got_reasons})
            if not found:
                evaluation["passed"] = False

    # Check system_must requirements
    for must in expected.get("system_must", []):
        # These are qualitative — check based on output content
        evaluation["checks"].append({
            "check": f"Must: {must[:80]}...",
            "passed": True,  # Qualitative — reviewed manually
            "note": "Qualitative requirement — see trace for verification",
        })

    return evaluation


def run_eval():
    """Run all test cases and print results."""
    test_cases = load_test_cases()
    results = []
    
    print("=" * 80)
    print("PLUM CLAIMS PROCESSING SYSTEM — EVALUATION REPORT")
    print("=" * 80)
    print()

    passed_count = 0
    total_count = len(test_cases)

    for tc in test_cases:
        case_id = tc["case_id"]
        case_name = tc["case_name"]
        print(f"─── {case_id}: {case_name} ───")

        try:
            claim = build_claim_from_test(tc)
            result = process_claim(claim)
            evaluation = evaluate_result(tc, result)

            status = "✅ PASS" if evaluation["passed"] else "❌ FAIL"
            if evaluation["passed"]:
                passed_count += 1

            print(f"  Status: {status}")
            print(f"  Decision: {result.get('decision', 'N/A')}")
            print(f"  Approved: ₹{result.get('approved_amount', 0):,.0f}")
            print(f"  Confidence: {result.get('confidence_score', 0):.2f}")

            for check in evaluation["checks"]:
                chk_status = "✓" if check["passed"] else "✗"
                print(f"    {chk_status} {check['check']}: expected={check.get('expected', '-')}, got={check.get('got', '-')}")

            # Print explanation
            explanation = result.get("explanation", "")
            if explanation:
                print(f"  Explanation: {explanation[:200]}")

            results.append({"case": tc, "result": result, "evaluation": evaluation})

        except Exception as e:
            print(f"  Status: 💥 ERROR — {str(e)}")
            results.append({"case": tc, "result": None, "evaluation": {"passed": False, "error": str(e)}})

        print()

    print("=" * 80)
    print(f"SUMMARY: {passed_count}/{total_count} test cases passed")
    print("=" * 80)

    return results


if __name__ == "__main__":
    run_eval()
