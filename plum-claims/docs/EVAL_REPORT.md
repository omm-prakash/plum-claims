# Evaluation Report — Plum Claims Processing System

**Date**: 2026-04-30
**Result**: **12/12 test cases passed** ✅

---

## Summary

| Metric | Value |
|--------|-------|
| Total test cases | 12 |
| Passed | 12 |
| Failed | 0 |
| Pass rate | **100%** |

---

## Test Case Results

### TC001: Wrong Document Uploaded ✅
| Check | Result |
|-------|--------|
| Decision | REJECTED (early stop) |
| Confidence | 0.99 |
| Doc verification failed | ✓ Pipeline stopped before making a claim decision |
| Specific error message | ✓ "A Hospital Bill is required for Consultation claims, but was not found. You uploaded: Prescription." |

**system_must**: ✓ Stop before making any claim decision · ✓ Tell the member specifically what was uploaded and what is needed · ✓ Not return a generic error

---

### TC002: Unreadable Document ✅
| Check | Result |
|-------|--------|
| Decision | REJECTED (early stop) |
| Confidence | 0.99 |
| Specific error message | ✓ "Your Pharmacy Bill (blurry_bill.jpg) could not be read — the image appears to be blurry or too low quality. Please re-upload a clearer photo or scan." |

**system_must**: ✓ Identify that the pharmacy bill cannot be read · ✓ Ask the member to re-upload that specific document · ✓ Not reject the claim outright — invite re-upload

---

### TC003: Documents Belong to Different Patients ✅
| Check | Result |
|-------|--------|
| Decision | REJECTED (early stop) |
| Confidence | 0.99 |
| Patient mismatch detected | ✓ "The documents belong to different patients: 'Rajesh Kumar' on PRESCRIPTION; 'Arjun Mehta' on HOSPITAL_BILL" |

**system_must**: ✓ Detect that the documents belong to different people · ✓ Surface names found on each document · ✓ Not proceed to a claim decision

---

### TC004: Clean Consultation — Full Approval ✅
| Check | Expected | Got |
|-------|----------|-----|
| Decision | APPROVED | ✓ APPROVED |
| Approved Amount | ₹1,350 | ✓ ₹1,350 |
| Confidence | > 0.85 | ✓ 0.95 |

**Calculation**: ₹1,500 × 0.90 (10% co-pay) = ₹1,350

---

### TC005: Waiting Period — Diabetes ✅
| Check | Expected | Got |
|-------|----------|-----|
| Decision | REJECTED | ✓ REJECTED |
| Rejection reason | WAITING_PERIOD | ✓ Found |
| Eligible date shown | — | ✓ "Eligible from 2024-11-30" |

**system_must**: ✓ State the date from which the member will be eligible

---

### TC006: Dental Partial Approval — Cosmetic Exclusion ✅
| Check | Expected | Got |
|-------|----------|-----|
| Decision | PARTIAL | ✓ PARTIAL |
| Approved Amount | ₹8,000 | ✓ ₹8,000 |

**Line item breakdown**:
- Root Canal Treatment (₹8,000) → APPROVED
- Teeth Whitening (₹4,000) → EXCLUDED (cosmetic procedure)

**system_must**: ✓ Itemize which line items were approved and rejected · ✓ State the reason for each rejection at line-item level

---

### TC007: MRI Without Pre-Authorization ✅
| Check | Expected | Got |
|-------|----------|-----|
| Decision | REJECTED | ✓ REJECTED |
| Rejection reason | PRE_AUTH_MISSING | ✓ Found |

**system_must**: ✓ Explain that pre-authorization was required · ✓ Tell the member how to resubmit with pre-auth

---

### TC008: Per-Claim Limit Exceeded ✅
| Check | Expected | Got |
|-------|----------|-----|
| Decision | REJECTED | ✓ REJECTED |
| Rejection reason | PER_CLAIM_EXCEEDED | ✓ Found |
| Message | — | ✓ "Claimed amount ₹7,500 exceeds the per-claim limit of ₹5,000" |

**system_must**: ✓ State the per-claim limit and the claimed amount clearly

---

### TC009: Fraud Signal — Multiple Same-Day Claims ✅
| Check | Expected | Got |
|-------|----------|-----|
| Decision | MANUAL_REVIEW | ✓ MANUAL_REVIEW |
| Fraud signals | — | ✓ "EXCESSIVE_SAME_DAY_CLAIMS: 4 claims on 2024-10-30, exceeding limit of 2" |

**system_must**: ✓ Flag the unusual same-day pattern · ✓ Route to manual review (not auto-reject) · ✓ Include specific signals in output

---

### TC010: Network Hospital — Discount Applied ✅
| Check | Expected | Got |
|-------|----------|-----|
| Decision | APPROVED | ✓ APPROVED |
| Approved Amount | ₹3,240 | ✓ ₹3,240 |

**Calculation**: ₹4,500 × 0.80 (20% network discount) = ₹3,600 → ₹3,600 × 0.90 (10% co-pay) = ₹3,240

**system_must**: ✓ Apply network discount before co-pay · ✓ Show breakdown in output

---

### TC011: Component Failure — Graceful Degradation ✅
| Check | Expected | Got |
|-------|----------|-----|
| Decision | APPROVED | ✓ APPROVED |
| Confidence | < 0.95 | ✓ 0.57 (degraded) |
| Component failures | — | ✓ ["document_extractor"] |
| Manual review note | — | ✓ "Component failure(s) detected. Confidence reduced. Manual review recommended." |

**system_must**: ✓ Not crash or return 500 · ✓ Indicate component failed · ✓ Lower confidence · ✓ Recommend manual review

---

### TC012: Excluded Treatment ✅
| Check | Expected | Got |
|-------|----------|-----|
| Decision | REJECTED | ✓ REJECTED |
| Confidence | > 0.9 | ✓ 0.95 |
| Rejection reason | EXCLUDED_CONDITION | ✓ Found |

---

## Bugs Fixed During Evaluation

1. **TC001 fix**: `DocVerificationResult.wrong_documents` field type changed from `dict[str, str]` to `dict[str, Any]` — the `uploaded_instead` value is a list, not a string.

2. **TC006 fix** (2 changes):
   - **Per-claim limit**: Categories with a higher sub-limit (dental = ₹10K) now override the generic per-claim limit (₹5K). Also, when line items have potential exclusions, hard rejection is deferred to let the amount calculator filter excluded items first.
   - **Exclusion detection**: `check_exclusions()` now correctly marks `excluded=True` when excluded line items are found (previously only checked `excluded_reasons` count, ignoring `excluded_items`).
