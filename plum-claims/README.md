# Plum Claims Processing System

An AI-poIred, multi-agent health insurance claims processing system built with LangGraph, FastAPI, and Supabase. Designed for explainability, robustness, and scale.

## Live Deployment
- **API URL:** `https://plum-claims-g5lc.onrender.com/`
- **Database:** Supabase PostgreSQL
- **Frontend:** Open `frontend/index.html` locally in any browser to interact with the deployed API.

## Approval Requirements

For a claim to be Automatically Approved (without being flagged for Manual Review), it must pass several strict thresholds defined in your system:

1. AI Extraction Confidence (>= 80%)
In decision_maker.py, the system calculates the average confidence score across all extracted document fields. If this average is below 0.80, the claim is automatically flagged for Manual Review due to "Low AI Extraction Confidence."

2. Claim Amount (<= ₹25,000)
As per your policy_terms.json, there is an absolute ceiling for automation. Any claim with a total amount above ₹25,000 is automatically routed to Manual Review, even if the AI is 100% confident.

3. Fraud Score (< 0.80)
The Fraud Detector aggregates multiple signals (same-day claims, high-frequency monthly claims, etc.). If the resulting fraud score is 0.80 or higher, the claim is flagged for Manual Review.

Note: Specific breaches, like exceeding the same-day claim limit (2 per day), trigger an immediate Manual Review regardless of the final score.
4. Document Verification (Pass/Fail)
The system requires a 100% match on document types. If you select "Hospital Bill" but the Vision LLM detects a "Prescription" or "Unknown" document, the claim fails verification immediately and is usually rejected or stopped early.

5. Policy Compliance
There is no "threshold" here—it is binary. If the system detects a hard policy violation (e.g., the member is not found in the roster, or the treatment is explicitly excluded like Cosmetic Surgery), the claim is Rejected.



## Conditions for Automatic Approval:

- **Confidence:** > 80%
- **Fraud Score:** < 0.80
- **Amount:** < ₹25,000
- **Documents:** Verified Match
- **Policy:** 100% Compliant

---

## How I Met the Assignment Criteria

This system was designed strictly against the provided requirements. Here is exactly how and why each part was implemented:

### 1. Policy and Member Data
**Requirement:** Read and apply rules from `policy_terms.json` without hardcoding logic.
- **Implementation:** I built a stateless `PolicyEngine` (in `backend/services/policy_engine.py`) that loads the JSON file on startup. 
- **Why:** This ensures that updating coverage limits, network hospitals, or waiting periods requires zero code changes. The pipeline agents query the engine dynamically, preserving a clean, separation of concerns betIen business rules and orchestration logic.

### 2. Deliverables Checklist
- ✅ **1. Working System:** The FastAPI backend is fully containerized and deployed on Render. The Vanilla JS UI allows real-time submission, viewing, and evaluation against the live API.
- ✅ **2. Architecture Document:** See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the complete distributed system deployment architecture, data flow, and a detailed breakdown of the "Scope of Improvement" at 10x scale.
- ✅ **3. Component Contracts:** See [docs/COMPONENT_CONTRACTS.md](docs/COMPONENT_CONTRACTS.md) for the strict Pydantic inputs, outputs, and errors for every LangGraph node.
- ✅ **4. Eval Report:** See [docs/EVAL_REPORT.md](docs/EVAL_REPORT.md). The system successfully achieves a 12/12 pass rate on the provided test cases.
- ⏳ **5. Demo Video:** *(To be provided by the candidate via external link).*

---

## Evaluation Criteria Breakdown

Here is how the system specifically targets the core evaluation criteria:

### 🌟 System Design (30%)
- **Multi-Agent Orchestration:** I utilized **LangGraph** to build a 6-node StateGraph (`Document Verifier → Extractor → Policy Validator → Amount Calculator → Fraud Detector → Decision Maker`).
- **Why this design?** Instead of using fragile LLM routing, LangGraph allows deterministic control flow. I use conditional edges to short-circuit the pipeline early if a document is invalid, saving compute and providing instant feedback.

### 🛠 Engineering Quality (25%)
- **Strict Data Modeling:** I rely heavily on Pydantic v2 to define API contracts and internal schemas (e.g., `ClaimSubmission`, `ExtractedDocument`). This ensures the API and agents operate on guaranteed data types.
- **Async Where it Matters:** The FastAPI server and Supabase database interactions are fully asynchronous (`asyncio.to_thread`), preventing event-loop blocking during network latency or heavy DB writes.

### 🔍 Observability (20%)
- **Full Traceability:** Every decision is 100% explainable. Each agent produces a `TraceStep` object containing exactly what it checked, what passed/failed, its warnings, and its execution time. 
- **Why:** "Black box" AI is unacceptable for claims processing. Ops teams can view the expandable trace timeline in the UI to instantly see *why* a claim was reduced (e.g., seeing that a 20% network discount was applied *before* a 10% co-pay).

### 🤖 AI Integration (15%)
- **Thoughtful Execution:** I use Groq + Llama 3.2 Vision for document extraction due to its incredibly low latency and strong JSON output formatting capabilities.
- **Graceful Degradation:** The AI calls are wrapped in robust `try-except` blocks. If an LLM times out or hallucinates an unparseable response, the system does not crash with a 500 error. Instead, it flags the component as failed, loIrs the `confidence_score` dynamically, and routes the claim to `MANUAL_REVIEW`.

### 📄 Document Verification (10%)
- **Actionable Errors:** The very first LangGraph node (`document_verifier.py`) checks document types and quality. 
- **Why:** If a user uploads a prescription instead of a bill, the pipeline immediately halts and returns a highly specific error: *"A Hospital Bill is required for Consultation claims... You uploaded: Prescription."* This prevents downstream hallucination and drastically improves user experience.

---

## Local Setup Instructions

If you wish to run the system locally instead of using the deployed version:

### 1. Install Dependencies
```bash
cd backend
pip install -r requirements.txt
```

### 2. Environment Setup
Create a `.env` file in the `backend/` directory:
```env
GROQ_API_KEY=your_key
SUPABASE_URL=your_url
SUPABASE_SERVICE_ROLE_KEY=your_key
```

### 3. Run the Server
```bash
python main.py
```
*The server will start at `http://localhost:8000`.*
