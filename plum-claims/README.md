# Plum Claims Processing System

AI-powered multi-agent health insurance claims processing system with explainable decisions and full observability.

## Quick Start

### 1. Install Dependencies
```bash
cd plum-claims/backend
pip install -r requirements.txt
```

### 2. Run the Server
```bash
cd plum-claims/backend
python main.py
```

The server starts at **http://localhost:8000**.

### 3. Open the UI
Navigate to **http://localhost:8000/** in your browser.

### 4. Run Test Cases
- Click **"Run Test Cases"** in the sidebar
- Click **"▶ Run All Tests"**
- All 12 test cases should show **ALL PASS**

### 5. Run Unit Tests
```bash
cd plum-claims/backend
python -m pytest tests/ -v
# 50 tests pass

python -m tests.eval_runner
# 12/12 test cases pass
```

---

## Project Structure

```
plum-claims/
├── backend/
│   ├── main.py                 # FastAPI server + endpoints
│   ├── config.py               # Environment configuration
│   ├── agents/
│   │   ├── graph.py            # LangGraph pipeline definition
│   │   ├── state.py            # Shared pipeline state schema
│   │   ├── document_verifier.py
│   │   ├── document_extractor.py
│   │   ├── policy_validator.py
│   │   ├── amount_calculator.py
│   │   ├── fraud_detector.py
│   │   └── decision_maker.py
│   ├── models/
│   │   ├── claim.py            # Claim data models
│   │   ├── decision.py         # Decision & trace models
│   │   └── policy.py           # Policy configuration models
│   ├── services/
│   │   └── policy_engine.py    # Policy rules engine (reads policy_terms.json)
│   └── tests/
│       ├── eval_runner.py      # 12-case evaluation suite
│       ├── test_policy_engine.py
│       └── test_agents.py
├── frontend/
│   ├── index.html              # Dashboard UI
│   ├── styles.css              # Design system
│   └── app.js                  # Application logic
└── docs/
    ├── ARCHITECTURE.md         # System design document
    ├── COMPONENT_CONTRACTS.md  # I/O contracts for all components
    └── EVAL_REPORT.md          # Full 12-case evaluation results
```

---

## Architecture

**6-Agent Pipeline** (LangGraph StateGraph):

```
Document Verifier → Document Extractor → Policy Validator → Amount Calculator → Fraud Detector → Decision Maker
```

- **Early exit**: If documents are invalid, pipeline short-circuits to Decision Maker → REJECTED
- **No hardcoded rules**: All policy logic reads from `policy_terms.json`
- **Graceful degradation**: Component failures reduce confidence but don't crash the pipeline
- **Full observability**: Every agent produces a `TraceStep` with checks, timing, and results

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design document.

---

## Deliverables

| Deliverable | Location |
|-------------|----------|
| Working system | `backend/` + `frontend/` |
| Architecture document | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Component contracts | [docs/COMPONENT_CONTRACTS.md](docs/COMPONENT_CONTRACTS.md) |
| Evaluation report | [docs/EVAL_REPORT.md](docs/EVAL_REPORT.md) |
| Unit tests | `backend/tests/` (50 tests) |
| Integration tests | `backend/tests/eval_runner.py` (12/12 pass) |
