"""
db/database.py — Supabase persistence layer for Plum Claims

Tables (PostgreSQL on Supabase)
--------------------------------
claims      : one row per claim submission (core fields + JSONB blob for full result)
documents   : one row per uploaded document, FK → claims.claim_id

Files are stored in Supabase Storage under the bucket defined by
SUPABASE_STORAGE_BUCKET (default: "claim-documents").
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import uuid
from datetime import datetime, date, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from supabase import create_client, Client, ClientOptions

from config import SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, SUPABASE_STORAGE_BUCKET


# ── JSON serialization helper ─────────────────────────────────────────────────

def _json_safe(obj: Any) -> Any:
    """Recursively convert a dict/list tree to JSON-serializable types."""
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Enum):
        return obj.value
    return obj


# ── Client singleton ──────────────────────────────────────────────────────────

_client: Client | None = None


def _get_client() -> Client:
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in .env"
            )
        _client = create_client(
            SUPABASE_URL,
            SUPABASE_SERVICE_ROLE_KEY,
            options=ClientOptions(postgrest_client_timeout=60),
        )
    return _client


# ── Startup ───────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Verify Supabase connection is reachable. Called once at server startup."""
    try:
        client = _get_client()
        # Lightweight ping — just fetch one row (or an empty result)
        client.table("claims").select("claim_id").limit(1).execute()
        print(f"[DB] Connected to Supabase project: {SUPABASE_URL}")
    except Exception as exc:
        print(f"[DB] WARNING — Supabase connection failed: {exc}")


# ── Storage helpers ───────────────────────────────────────────────────────────

def upload_file_to_storage(local_path: str, claim_id: str) -> str | None:
    """
    Upload a local file to Supabase Storage and return its public URL.
    Returns None if the upload fails (non-fatal).
    """
    try:
        client = _get_client()
        path = Path(local_path)
        mime_type, _ = mimetypes.guess_type(str(path))
        mime_type = mime_type or "application/octet-stream"

        # Storage key: claim_id/uuid_filename to avoid collisions
        storage_key = f"{claim_id}/{uuid.uuid4().hex[:8]}_{path.name}"

        with open(path, "rb") as f:
            client.storage.from_(SUPABASE_STORAGE_BUCKET).upload(
                path=storage_key,
                file=f,
                file_options={"content-type": mime_type},
            )

        # Build public URL
        public_url = (
            f"{SUPABASE_URL}/storage/v1/object/public/"
            f"{SUPABASE_STORAGE_BUCKET}/{storage_key}"
        )
        return public_url
    except Exception as exc:
        print(f"[Storage] Upload failed for {local_path}: {exc}")
        return None


# ── Write operations ──────────────────────────────────────────────────────────

def save_claim(claim_data: dict[str, Any], result: dict[str, Any]) -> None:
    """
    Persist a processed claim and its documents to Supabase.

    Parameters
    ----------
    claim_data : dict
        Output of ClaimSubmission.model_dump()
    result : dict
        Output of process_claim() — the full pipeline result
    """
    client = _get_client()
    claim_id = claim_data["claim_id"]
    submitted_at = datetime.now(timezone.utc).isoformat()

    decision = result.get("decision")
    approved_amount = result.get("approved_amount")
    confidence_score = result.get("confidence_score")

    # ── Upsert claim row ──────────────────────────────────────────────────────
    claim_row = _json_safe({
        "claim_id": claim_id,
        "member_id": claim_data.get("member_id", ""),
        "policy_id": claim_data.get("policy_id", "PLUM_GHI_2024"),
        "claim_category": str(claim_data.get("claim_category", "")),
        "treatment_date": str(claim_data.get("treatment_date", "")),
        "claimed_amount": float(claim_data.get("claimed_amount", 0)),
        "hospital_name": claim_data.get("hospital_name"),
        "ytd_claims_amount": float(claim_data.get("ytd_claims_amount", 0)),
        "decision": str(decision) if decision else None,
        "approved_amount": float(approved_amount) if approved_amount is not None else None,
        "confidence_score": float(confidence_score) if confidence_score is not None else None,
        "submitted_at": submitted_at,
        "result_json": result,
        "claim_json": claim_data,
    })
    client.table("claims").upsert(claim_row).execute()

    # ── Delete old document rows then re-insert ───────────────────────────────
    client.table("documents").delete().eq("claim_id", claim_id).execute()

    doc_rows = []
    for doc in claim_data.get("documents", []):
        local_file_path = doc.get("file_path")
        storage_url: str | None = None

        # If there's a real file on disk, push it to Supabase Storage
        if local_file_path and Path(local_file_path).exists():
            storage_url = upload_file_to_storage(local_file_path, claim_id)

        content = doc.get("content")
        doc_rows.append({
            "claim_id": claim_id,
            "file_id": doc.get("file_id", ""),
            "file_name": doc.get("file_name"),
            "actual_type": str(doc.get("actual_type", "")),
            "quality": str(doc.get("quality", "GOOD")),
            "patient_name_on_doc": doc.get("patient_name_on_doc"),
            "file_path": storage_url or local_file_path,   # public URL preferred
            "content_json": content,
            "created_at": submitted_at,
        })

    if doc_rows:
        client.table("documents").insert(doc_rows).execute()


# ── Read operations ───────────────────────────────────────────────────────────

def get_all_claims() -> list[dict[str, Any]]:
    """Return summary rows for every claim (no full JSON blobs)."""
    client = _get_client()
    response = (
        client.table("claims")
        .select(
            "claim_id, member_id, claim_category, claimed_amount, "
            "decision, approved_amount, confidence_score, submitted_at"
        )
        .order("submitted_at", desc=True)
        .execute()
    )
    return response.data or []


def get_claim(claim_id: str) -> dict[str, Any] | None:
    """Return the full claim row including parsed result and claim JSON."""
    client = _get_client()

    claim_response = (
        client.table("claims")
        .select("*")
        .eq("claim_id", claim_id)
        .limit(1)
        .execute()
    )
    rows = claim_response.data
    if not rows:
        return None

    data = rows[0]
    # Supabase returns JSONB columns as dicts already — rename to match old API
    data["result"] = data.pop("result_json", {}) or {}
    data["claim"] = data.pop("claim_json", {}) or {}

    # Attach document rows
    doc_response = (
        client.table("documents")
        .select("*")
        .eq("claim_id", claim_id)
        .order("id")
        .execute()
    )
    docs = []
    for dr in (doc_response.data or []):
        dr["content"] = dr.pop("content_json", None)
        docs.append(dr)
    data["documents"] = docs

    return data


def get_documents_for_claim(claim_id: str) -> list[dict[str, Any]]:
    """Return all document rows for a given claim."""
    client = _get_client()
    response = (
        client.table("documents")
        .select("*")
        .eq("claim_id", claim_id)
        .order("id")
        .execute()
    )
    result = []
    for row in (response.data or []):
        row["content"] = row.pop("content_json", None)
        result.append(row)
    return result


# ── Async-safe wrappers (use these from FastAPI async endpoints) ───────────────

async def async_save_claim(claim_data: dict[str, Any], result: dict[str, Any]) -> None:
    """Thread-safe async wrapper for save_claim."""
    await asyncio.to_thread(save_claim, claim_data, result)


async def async_get_all_claims() -> list[dict[str, Any]]:
    """Thread-safe async wrapper for get_all_claims."""
    return await asyncio.to_thread(get_all_claims)


async def async_get_claim(claim_id: str) -> dict[str, Any] | None:
    """Thread-safe async wrapper for get_claim."""
    return await asyncio.to_thread(get_claim, claim_id)

