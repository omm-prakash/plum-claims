# Architecture Document — Plum Claims Processing System

## 1. System Overview

The Plum Claims Processing System is an AI-powered, multi-agent pipeline that automates health insurance claims adjudication. It processes claims through six sequential agents, each performing a specialized task, and produces an explainable decision with a full audit trail.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Plum Claims Processing System                       │
│                                                                            │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌─────────┐ │
│  │  FastAPI  │──▶│ LangGraph│──▶│  Policy  │──▶│ In-Memory│──▶│Frontend │ │
│  │  Server   │   │ Pipeline │   │  Engine  │   │  Store   │   │   UI    │ │
│  └──────────┘   └──────────┘   └──────────┘   └──────────┘   └─────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Technology Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| **API Framework** | FastAPI | Async-native, auto-generated docs, Pydantic validation |
| **Agent Orchestration** | LangGraph | Directed graph with conditional edges, state management |
| **Data Validation** | Pydantic v2 | Strict typing, JSON schema generation |
| **Policy Engine** | Custom Python | Stateless, loads from `policy_terms.json` — zero hardcoded rules |
| **Frontend** | Vanilla HTML/CSS/JS | No build step needed, served by FastAPI |
| **Testing** | pytest + custom eval runner | 50+ unit tests + 12 integration test cases |

---

## 2. Multi-Agent Pipeline Architecture

The core of the system is a **LangGraph StateGraph** that processes claims through 6 sequential agents. Each agent reads from and writes to a shared `ClaimPipelineState` (TypedDict).

```
                     ┌─────────────────────┐
                     │   Claim Submission   │
                     └──────────┬──────────┘
                                │
                     ┌──────────▼──────────┐
                     │ Document Verifier   │ ←── Early exit if docs invalid
                     │ (wrong type, unread-│
                     │  able, name mismatch)│
                     └──────────┬──────────┘
                                │
                    ┌───────────┴───────────┐
                    │ should_stop = True?   │
                    ├────── YES ────────────┼──────────┐
                    │                       │          │
                    │       NO              │          ▼
                    └───────┬───────────────┘   ┌─────────────┐
                            │                   │  Decision   │
                 ┌──────────▼──────────┐        │  Maker      │
                 │ Document Extractor  │        │  (REJECTED) │
                 │ (structured data)   │        └─────────────┘
                 └──────────┬──────────┘
                            │
                 ┌──────────▼──────────┐
                 │ Policy Validator    │
                 │ (waiting periods,   │
                 │  exclusions, limits)│
                 └──────────┬──────────┘
                            │
                 ┌──────────▼──────────┐
                 │ Amount Calculator   │
                 │ (discount → copay → │
                 │  sub-limit → cap)   │
                 └──────────┬──────────┘
                            │
                 ┌──────────▼──────────┐
                 │ Fraud Detector      │
                 │ (same-day, monthly, │
                 │  high-value signals)│
                 └──────────┬──────────┘
                            │
                 ┌──────────▼──────────┐
                 │ Decision Maker      │
                 │ (aggregate results, │
                 │  confidence scoring)│
                 └──────────┴──────────┘
                            │
                     ┌──────▼──────┐
                     │   Result    │
                     │  APPROVED / │
                     │  PARTIAL /  │
                     │  REJECTED / │
                     │  MANUAL_REV │
                     └─────────────┘
```

### Key Design Decisions

**1. Conditional Early Exit**
The graph uses a conditional edge after `document_verifier`. If documents are invalid (wrong type, unreadable, patient name mismatch), the pipeline short-circuits directly to `decision_maker`, which issues a `REJECTED` decision. This avoids wasted computation and gives the member a clear, actionable error message.

**2. Shared State (not message passing)**
Agents communicate via a shared `ClaimPipelineState` TypedDict, not via LLM message passing. This ensures:
- Deterministic behavior (no LLM hallucination in routing)
- Full observability (every field is inspectable)
- Fast execution (no LLM calls for orchestration)

**3. Policy Engine Separation**
All policy rules are loaded from `policy_terms.json` at startup. No agent contains hardcoded limits, exclusion lists, or waiting periods. This means policy changes require only a JSON file update — zero code changes.

**4. Amount Calculation Order**
The amount calculator applies financial adjustments in a specific, mathematically correct order:
1. Filter excluded line items
2. Apply network discount (if applicable)
3. Apply co-pay percentage
4. Cap at category sub-limit
5. Cap at per-claim limit
6. Cap at remaining annual limit

This order matters: applying discount before co-pay (not after) gives the correct result. (TC010 verifies: ₹4,500 × 0.80 × 0.90 = ₹3,240.)

---

## 3. Data Flow

### Request → Response

```
POST /api/claims/submit
     │
     ▼
ClaimSubmission (Pydantic model)
     │  member_id, category, amount, documents[]
     ▼
build_claims_pipeline() → LangGraph StateGraph
     │
     ├─ document_verifier → DocVerificationResult
     ├─ document_extractor → ExtractedDocument[]
     ├─ policy_validator → PolicyCheckResult
     ├─ amount_calculator → AmountBreakdown
     ├─ fraud_detector → FraudCheckResult
     └─ decision_maker → DecisionResult
     │
     ▼
DecisionResult (JSON response)
     │  decision, approved_amount, confidence_score,
     │  explanation, trace[], amount_breakdown,
     │  doc_verification, policy_check, fraud_check
     ▼
Frontend renders decision + trace timeline
```

### State Schema

```python
class ClaimPipelineState(TypedDict):
    claim: dict              # Original submission
    documents: list[dict]    # Uploaded documents
    doc_verification: dict   # From agent 1
    extracted_data: list     # From agent 2
    policy_check: dict       # From agent 3
    amount_calc: dict        # From agent 4
    fraud_check: dict        # From agent 5
    decision: dict           # From agent 6
    trace: list[dict]        # Audit trail (all agents append)
    errors: list[str]        # Error log
    should_stop: bool        # Early exit flag
    component_failures: list # Degraded components
    hospital_name: str       # Extracted hospital
    diagnosis: str           # Extracted diagnosis
    treatment: str           # Extracted treatment
    line_items: list[dict]   # Extracted line items
```

---

## 4. Error Handling & Graceful Degradation

### Strategy

1. **Document errors** → `REJECTED` with specific actionable message (TC001–TC003)
2. **Policy violations** → `REJECTED` with violation codes and explanations (TC005, TC007, TC008)
3. **Partial exclusions** → `PARTIAL` approval with line-item breakdown (TC006)
4. **Fraud signals** → `MANUAL_REVIEW` with flagged signals (TC009)
5. **Component failure** → Pipeline continues with degraded confidence (TC011)
6. **Unhandled exceptions** → `MANUAL_REVIEW` with error trace (never a 500 to the user)

### Component Failure Handling (TC011)

When `simulate_component_failure=True`, the document extractor enters **degraded mode**:
- Falls back to basic field extraction from document content
- Marks extraction confidence as reduced (0.7 instead of 0.95)
- Adds `document_extractor` to `component_failures` list
- Pipeline continues through remaining agents
- Decision maker reduces confidence score by 40% for each failed component
- Final response includes `requires_manual_review_note`

---

## 5. Observability

Every agent produces a `TraceStep` that captures:
- `agent_name` and `display_name`
- `started_at`, `completed_at`, `duration_ms`
- `status`: SUCCESS / WARNING / FAILED / SKIPPED
- `input_summary`: What the agent received
- `output_summary`: What the agent produced
- `checks_performed`: List of individual checks with pass/fail
- `errors` and `warnings`
- `message`: Human-readable summary

The frontend renders these as an **expandable trace timeline**, allowing ops teams to drill into exactly why a claim was approved, rejected, or flagged.

---

## 6. Scaling Considerations (10x Load)

At 10x load (~10,000+ claims/day), the following changes would be needed:

| Current | At Scale |
|---------|----------|
| In-memory `claims_store` dict | PostgreSQL with async driver (asyncpg) |
| Single uvicorn worker | Multiple workers behind nginx/Gunicorn, horizontal scaling |
| Synchronous pipeline | Celery/Redis task queue for async processing |
| No caching | Redis cache for policy engine (it's stateless, ideal for caching) |
| Single-file policy JSON | Database-backed policy store with version history |
| No rate limiting | API rate limiting per member/company |
| No monitoring | Prometheus metrics + Grafana dashboards |
| File-based logging | Structured logging to ELK/Loki stack |

### What Wouldn't Change
- The LangGraph pipeline architecture (agents are stateless, horizontally scalable)
- The policy engine interface (swap storage backend, keep the same API)
- The Pydantic models (they're the contract)
- The trace/observability structure (just route to a persistent store)

---

## 7. Security Considerations

- **Input validation**: All inputs validated via Pydantic models before entering the pipeline
- **CORS**: Configured via environment variables (currently `*` for development)
- **No PII in logs**: Trace steps contain summaries, not raw patient data
- **API authentication**: Not implemented (assignment scope) but would add JWT-based auth at scale
- **Document handling**: Currently JSON-based content; production would need secure file upload with virus scanning

---

## 8. What Was Considered and Rejected

| Approach | Why Rejected |
|----------|-------------|
| **LLM-based routing** between agents | Non-deterministic, slower, harder to test |
| **Microservices** (one per agent) | Over-engineered for this scope; LangGraph gives same isolation |
| **Database-first** approach | In-memory store is sufficient; avoids setup complexity |
| **React/Next.js frontend** | Overkill for a claims review UI; vanilla JS loads instantly |
| **LLM for amount calculation** | Math must be deterministic; LLMs can't be trusted with financial calculations |
| **Parallel agent execution** | Agents have dependencies (extractor needs verifier output); sequential is correct |
