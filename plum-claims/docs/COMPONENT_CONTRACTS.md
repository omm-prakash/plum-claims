# Component Contracts — Plum Claims Processing System

This document defines the exact input/output contract for every component in the pipeline.

---

## 1. Document Verification Agent

**Purpose**: Validates that submitted documents are correct type, readable, and belong to the same patient.

### Input (from `ClaimPipelineState`)
| Field | Type | Description |
|-------|------|-------------|
| `claim` | `dict` | Full claim submission (member_id, category, etc.) |
| `documents` | `list[dict]` | List of uploaded documents with `actual_type`, `quality`, `patient_name_on_doc` |

### Output (written to state)
| Field | Type | Description |
|-------|------|-------------|
| `doc_verification` | `DocVerificationResult` | Verification result |
| `should_stop` | `bool` | `True` if pipeline should exit early |
| `trace` | `list[TraceStep]` | Appended with this agent's trace |

### DocVerificationResult Schema
```json
{
  "passed": false,
  "missing_documents": ["HOSPITAL_BILL"],
  "wrong_documents": [{"file_id": "F001", "expected": "HOSPITAL_BILL", "uploaded_instead": ["PRESCRIPTION"]}],
  "unreadable_documents": [{"file_id": "F002", "type": "PHARMACY_BILL", "reason": "Document quality is UNREADABLE"}],
  "patient_name_mismatch": {"names_found": ["Rajesh Kumar", "Arjun Mehta"], "mismatch": true},
  "error_message": "Specific error message for the member",
  "details": ["List of human-readable check results"]
}
```

### Error Cases
| Scenario | Behavior |
|----------|----------|
| Wrong document type | `passed=False`, `should_stop=True`, lists expected vs actual |
| Unreadable document | `passed=False`, `should_stop=True`, identifies which doc |
| Patient name mismatch | `passed=False`, `should_stop=True`, shows conflicting names |
| No documents | `passed=False`, `should_stop=True`, lists all required docs |

---

## 2. Document Extraction Agent

**Purpose**: Extracts structured data from documents (diagnosis, treatment, line items, amounts).

### Input
| Field | Type | Description |
|-------|------|-------------|
| `documents` | `list[dict]` | Documents with optional `content` field |
| `claim.simulate_component_failure` | `bool` | If true, enters degraded mode |

### Output
| Field | Type | Description |
|-------|------|-------------|
| `extracted_data` | `list[ExtractedDocument]` | Structured extraction per document |
| `diagnosis` | `str \| None` | Extracted diagnosis text |
| `treatment` | `str \| None` | Extracted treatment text |
| `line_items` | `list[dict] \| None` | Extracted line items with `description` and `amount` |
| `hospital_name` | `str \| None` | Extracted hospital name |
| `component_failures` | `list[str]` | Appended with `"document_extractor"` on failure |

### ExtractedDocument Schema
```json
{
  "file_id": "F001",
  "document_type": "PRESCRIPTION",
  "fields": [
    {"field_name": "diagnosis", "value": "Viral Fever", "confidence": 0.95, "source_document": "F001"}
  ],
  "extraction_confidence": 0.95,
  "warnings": []
}
```

### Error Cases
| Scenario | Behavior |
|----------|----------|
| Component failure simulated | Degraded extraction with reduced confidence (0.70) |
| No content in document | Skips extraction, adds warning |
| Missing fields | Fields extracted with lower confidence |

---

## 3. Policy Validation Agent

**Purpose**: Checks claim eligibility against all policy rules.

### Input
| Field | Type | Description |
|-------|------|-------------|
| `claim` | `dict` | Full claim (member_id, category, amount, treatment_date) |
| `diagnosis` | `str` | From extraction |
| `treatment` | `str` | From extraction |
| `line_items` | `list[dict]` | From extraction |

### Output
| Field | Type | Description |
|-------|------|-------------|
| `policy_check` | `PolicyCheckResult` | Validation result |

### PolicyCheckResult Schema
```json
{
  "eligible": false,
  "violations": [
    {"code": "WAITING_PERIOD", "message": "Waiting period of 90 days for Diabetes..."},
    {"code": "PER_CLAIM_EXCEEDED", "message": "Claimed amount ₹7,500 exceeds per-claim limit of ₹5,000"},
    {"code": "EXCLUDED_CONDITION", "message": "'Teeth Whitening' is excluded", "excluded_items": ["Teeth Whitening"]},
    {"code": "PRE_AUTH_MISSING", "message": "Pre-authorization required for MRI above ₹10,000"}
  ],
  "warnings": [],
  "checks_performed": [
    {"check": "Member eligibility", "status": "PASS", "detail": "Member EMP001 found"},
    {"check": "Per-claim limit", "status": "FAIL", "detail": "₹7,500 exceeds ₹5,000 limit"}
  ]
}
```

### Checks Performed (in order)
1. **Member eligibility** — Does the member exist?
2. **Per-claim limit** — Is claimed amount within limit? (Category sub-limit overrides if higher)
3. **Waiting period** — Has the member waited long enough for this condition?
4. **Exclusions** — Is the diagnosis/treatment excluded? Are line items excluded?
5. **Pre-authorization** — Is pre-auth required and missing?
6. **Category coverage** — Is this category covered at all?
7. **Minimum claim amount** — Is the claim above ₹500?

---

## 4. Amount Calculation Agent

**Purpose**: Calculates the approved amount with a detailed breakdown.

### Input
| Field | Type | Description |
|-------|------|-------------|
| `claim` | `dict` | Full claim |
| `policy_check` | `dict` | From policy validator |
| `line_items` | `list[dict]` | Extracted line items |
| `hospital_name` | `str` | For network hospital check |

### Output
| Field | Type | Description |
|-------|------|-------------|
| `amount_calc` | `AmountBreakdown` | Detailed breakdown |

### AmountBreakdown Schema
```json
{
  "original_amount": 4500,
  "eligible_amount": 4500,
  "network_discount_applied": 900,
  "amount_after_discount": 3600,
  "copay_amount": 360,
  "amount_after_copay": 3240,
  "sub_limit_applied": 2000,
  "per_claim_limit_applied": null,
  "annual_limit_remaining": 45000,
  "final_approved_amount": 3240,
  "line_item_decisions": [
    {"description": "Consultation Fee", "claimed_amount": 1500, "approved_amount": 1500, "status": "APPROVED", "reason": null},
    {"description": "Teeth Whitening", "claimed_amount": 4000, "approved_amount": 0, "status": "EXCLUDED", "reason": "Excluded procedure"}
  ],
  "calculation_steps": [
    "Step 1: Eligible amount = ₹4,500",
    "Step 2: Network discount (20%) = -₹900 → ₹3,600",
    "Step 3: Co-pay (10%) = -₹360 → ₹3,240",
    "Final approved amount: ₹3,240"
  ]
}
```

### Calculation Order
1. Filter excluded line items → eligible amount
2. Network discount (if network hospital)
3. Co-pay percentage
4. Category sub-limit cap
5. Per-claim limit cap
6. Annual remaining limit cap

---

## 5. Fraud Detection Agent

**Purpose**: Detects suspicious patterns and assigns a fraud score.

### Input
| Field | Type | Description |
|-------|------|-------------|
| `claim` | `dict` | Full claim with `claims_history` |

### Output
| Field | Type | Description |
|-------|------|-------------|
| `fraud_check` | `FraudCheckResult` | Fraud analysis |

### FraudCheckResult Schema
```json
{
  "fraud_score": 0.45,
  "signals": [
    {"type": "EXCESSIVE_SAME_DAY_CLAIMS", "detail": "4 claims on 2024-10-30, limit is 2", "severity": 0.4}
  ],
  "requires_manual_review": true,
  "details": ["Human-readable signal descriptions"]
}
```

### Signals Checked
| Signal | Threshold | Score Impact |
|--------|-----------|-------------|
| Same-day claims | > 2 per day | +0.30 |
| Monthly claims | > 6 per month | +0.20 |
| High-value claim | > ₹25,000 | +0.15 |

---

## 6. Decision Maker Agent

**Purpose**: Aggregates all agent results and produces the final decision.

### Input
| Field | Type | Description |
|-------|------|-------------|
| `claim` | `dict` | Full claim |
| `doc_verification` | `dict` | From agent 1 |
| `policy_check` | `dict` | From agent 3 |
| `amount_calc` | `dict` | From agent 4 |
| `fraud_check` | `dict` | From agent 5 |
| `component_failures` | `list[str]` | Failed components |
| `should_stop` | `bool` | Early exit flag |

### Output
| Field | Type | Description |
|-------|------|-------------|
| `decision` | `DecisionResult` | Final decision with full trace |

### DecisionResult Schema
```json
{
  "claim_id": "CLM_ABC12345",
  "decision": "APPROVED",
  "approved_amount": 3240,
  "claimed_amount": 4500,
  "confidence_score": 0.95,
  "reasons": ["All checks passed"],
  "explanation": "Claim approved for ₹3,240 (claimed: ₹4,500).\n...",
  "amount_breakdown": { ... },
  "doc_verification": { ... },
  "policy_check": { ... },
  "fraud_check": { ... },
  "trace": [ ... ],
  "component_failures": [],
  "requires_manual_review_note": null,
  "processed_at": "2024-11-01T10:30:00"
}
```

### Decision Logic
| Condition | Decision |
|-----------|----------|
| Doc verification failed | `REJECTED` |
| Hard policy violations (waiting period, pre-auth, excluded) | `REJECTED` |
| Partial exclusion (some line items excluded) | `PARTIAL` |
| Fraud signals → manual review | `MANUAL_REVIEW` |
| Component failure | Decision continues but confidence reduced |
| All checks pass | `APPROVED` |

---

## 7. Policy Engine Service

**Purpose**: Single source of truth for all policy rules. Loads `policy_terms.json` once and provides typed query methods.

### Public API
```python
class PolicyEngine:
    def get_member(member_id: str) -> Member | None
    def get_primary_member(member_id: str) -> Member | None
    def get_document_requirements(category: str) -> DocumentRequirement | None
    def get_category_config(category: str) -> OPDCategory | None
    def get_sub_limit(category: str) -> float
    def get_copay_percent(category: str) -> float
    def get_network_discount_percent(category: str) -> float
    def get_per_claim_limit() -> float
    def get_annual_opd_limit() -> float
    def is_network_hospital(hospital_name: str) -> bool
    def check_waiting_period(member, diagnosis, treatment_date) -> dict
    def check_exclusions(diagnosis, treatment, category, line_items) -> dict
    def check_pre_auth_required(category, line_items, claimed_amount) -> dict
    def check_per_claim_limit(claimed_amount) -> dict
    def get_fraud_thresholds() -> dict
    def get_minimum_claim_amount() -> float
```

### Singleton Pattern
The engine is instantiated once via `get_policy_engine()` and reused across all requests. It is **stateless** — it reads the policy file at startup and provides pure query functions.

---

## 8. FastAPI Endpoints

| Method | Path | Description | Input | Output |
|--------|------|-------------|-------|--------|
| `GET` | `/api/health` | Health check | — | `{"status": "healthy"}` |
| `POST` | `/api/claims/test` | Submit test case | `TestClaimRequest` | `DecisionResult` |
| `POST` | `/api/claims/submit` | Submit from UI | `UIClaimRequest` | `DecisionResult` |
| `GET` | `/api/claims` | List all claims | — | `{"claims": [...], "total": N}` |
| `GET` | `/api/claims/{id}` | Get claim detail | claim_id | Full claim + result |
| `GET` | `/api/policy/summary` | Policy overview | — | Coverage, hospitals, categories |
| `GET` | `/api/members` | List members | — | Member roster |
| `GET` | `/` | Serve frontend | — | HTML page |
| `GET` | `/test_cases.json` | Serve test cases | — | JSON file |
