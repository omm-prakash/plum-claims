"""
FastAPI Main Application — Health Insurance Claims Processing System

Endpoints:
  POST /api/claims/submit   — Submit a new claim (JSON or multipart)
  POST /api/claims/test      — Submit a test case (JSON, no files)
  GET  /api/claims            — List all processed claims
  GET  /api/claims/{id}       — Get a specific claim with full trace
  GET  /api/policy/summary    — Get policy summary for UI
  GET  /api/members           — List all members
  GET  /api/health            — Health check
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, date
from enum import Enum
from typing import Any, Optional

from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import CORS_ORIGINS, API_HOST, API_PORT
from models.claim import ClaimSubmission, ClaimCategory, DocumentUpload, DocumentType, DocumentQuality, DocumentContent, ClaimHistoryEntry
from agents.graph import process_claim
from services.policy_engine import get_policy_engine

# ── App Setup ────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Plum Claims Processing System",
    description="AI-powered health insurance claims processing with multi-agent pipeline",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory store (sufficient for assignment scope) ────────────────────────

claims_store: dict[str, dict[str, Any]] = {}


def _serialize(obj: Any) -> Any:
    """Recursively convert a dict/list tree so it's JSON-safe."""
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    return obj


# ── Request Models ───────────────────────────────────────────────────────────

class TestClaimRequest(BaseModel):
    """Request body for submitting a test case."""
    member_id: str
    policy_id: str = "PLUM_GHI_2024"
    claim_category: str
    treatment_date: str
    claimed_amount: float
    hospital_name: Optional[str] = None
    ytd_claims_amount: float = 0.0
    claims_history: list[dict[str, Any]] = []
    simulate_component_failure: bool = False
    documents: list[dict[str, Any]] = []


class UIClaimRequest(BaseModel):
    """Request body for submitting a claim from the UI."""
    member_id: str
    claim_category: str
    treatment_date: str
    claimed_amount: float
    hospital_name: Optional[str] = None
    documents: list[dict[str, Any]] = []


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


@app.post("/api/claims/test")
async def submit_test_claim(request: TestClaimRequest):
    """Submit a test case through the pipeline (JSON input, no file uploads)."""
    try:
        # Parse documents
        docs = []
        for d in request.documents:
            content = None
            if "content" in d and d["content"]:
                content = DocumentContent(**d["content"])
            docs.append(DocumentUpload(
                file_id=d.get("file_id", f"F{uuid.uuid4().hex[:6].upper()}"),
                file_name=d.get("file_name"),
                actual_type=DocumentType(d["actual_type"]),
                quality=DocumentQuality(d.get("quality", "GOOD")),
                patient_name_on_doc=d.get("patient_name_on_doc"),
                content=content,
            ))

        # Parse claims history
        history = [ClaimHistoryEntry(**h) for h in request.claims_history]

        claim = ClaimSubmission(
            member_id=request.member_id,
            policy_id=request.policy_id,
            claim_category=ClaimCategory(request.claim_category),
            treatment_date=request.treatment_date,
            claimed_amount=request.claimed_amount,
            hospital_name=request.hospital_name,
            ytd_claims_amount=request.ytd_claims_amount,
            claims_history=history,
            documents=docs,
            simulate_component_failure=request.simulate_component_failure,
        )

        result = process_claim(claim)
        claims_store[claim.claim_id] = {
            "claim": claim.model_dump(),
            "result": result,
            "submitted_at": datetime.utcnow().isoformat(),
        }

        return JSONResponse(content=_serialize(result))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/claims/submit")
async def submit_claim(request: UIClaimRequest):
    """Submit a claim from the UI."""
    try:
        docs = []
        for d in request.documents:
            content = None
            if "content" in d and d["content"]:
                content = DocumentContent(**d["content"])
            docs.append(DocumentUpload(
                file_id=d.get("file_id", f"F{uuid.uuid4().hex[:6].upper()}"),
                file_name=d.get("file_name"),
                actual_type=DocumentType(d["actual_type"]),
                quality=DocumentQuality(d.get("quality", "GOOD")),
                patient_name_on_doc=d.get("patient_name_on_doc"),
                content=content,
            ))

        claim = ClaimSubmission(
            member_id=request.member_id,
            claim_category=ClaimCategory(request.claim_category),
            treatment_date=request.treatment_date,
            claimed_amount=request.claimed_amount,
            hospital_name=request.hospital_name,
            documents=docs,
        )

        result = process_claim(claim)
        claims_store[claim.claim_id] = {
            "claim": claim.model_dump(),
            "result": result,
            "submitted_at": datetime.utcnow().isoformat(),
        }

        return JSONResponse(content=_serialize(result))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/claims")
async def list_claims():
    """List all processed claims."""
    items = []
    for claim_id, data in claims_store.items():
        result = data.get("result", {})
        items.append({
            "claim_id": claim_id,
            "member_id": data["claim"]["member_id"],
            "category": data["claim"]["claim_category"],
            "claimed_amount": data["claim"]["claimed_amount"],
            "decision": result.get("decision", "UNKNOWN"),
            "approved_amount": result.get("approved_amount", 0),
            "confidence_score": result.get("confidence_score", 0),
            "submitted_at": data.get("submitted_at"),
        })
    return {"claims": _serialize(items), "total": len(items)}


@app.get("/api/claims/{claim_id}")
async def get_claim(claim_id: str):
    """Get a specific claim with full decision and trace."""
    if claim_id not in claims_store:
        raise HTTPException(status_code=404, detail=f"Claim {claim_id} not found")
    return _serialize(claims_store[claim_id])


@app.get("/api/policy/summary")
async def get_policy_summary():
    """Get a summary of the policy for UI display."""
    engine = get_policy_engine()
    p = engine.policy
    return {
        "policy_id": p.policy_id,
        "policy_name": p.policy_name,
        "insurer": p.insurer,
        "company": p.policy_holder.company_name,
        "sum_insured": p.coverage.sum_insured_per_employee,
        "annual_opd_limit": p.coverage.annual_opd_limit,
        "per_claim_limit": p.coverage.per_claim_limit,
        "categories": list(p.opd_categories.keys()),
        "network_hospitals": p.network_hospitals,
    }


@app.get("/api/members")
async def list_members():
    """List all policy members."""
    engine = get_policy_engine()
    return {
        "members": [m.model_dump() for m in engine.policy.members],
        "total": len(engine.policy.members),
    }


# ── Static File Serving (Frontend) ───────────────────────────────────────────

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"
ROOT_DIR = Path(__file__).parent.parent.parent  # Assignment root for test_cases.json

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")

@app.get("/test_cases.json")
async def get_test_cases():
    path = ROOT_DIR / "test_cases.json"
    if path.exists():
        return FileResponse(str(path), media_type="application/json")
    raise HTTPException(status_code=404)

@app.get("/")
async def serve_frontend():
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "Plum Claims API. Frontend not found at " + str(FRONTEND_DIR)}


# ── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=API_HOST, port=API_PORT)
