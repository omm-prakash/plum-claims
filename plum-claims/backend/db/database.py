"""
db/database.py — SQLite persistence layer for Plum Claims

Tables
------
claims      : one row per claim submission (core fields + JSON blob for full result)
documents   : one row per uploaded document, FK → claims.claim_id
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

# ── DB location — backend/db/plum_claims.db ──────────────────────────────────

DB_DIR = Path(__file__).parent
DB_PATH = DB_DIR / "plum_claims.db"


# ── Schema ────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS claims (
    claim_id          TEXT PRIMARY KEY,
    member_id         TEXT NOT NULL,
    policy_id         TEXT NOT NULL,
    claim_category    TEXT NOT NULL,
    treatment_date    TEXT NOT NULL,
    claimed_amount    REAL NOT NULL,
    hospital_name     TEXT,
    ytd_claims_amount REAL NOT NULL DEFAULT 0,
    decision          TEXT,
    approved_amount   REAL,
    confidence_score  REAL,
    submitted_at      TEXT NOT NULL,
    result_json       TEXT,          -- full pipeline result as JSON
    claim_json        TEXT           -- full ClaimSubmission as JSON
);

CREATE TABLE IF NOT EXISTS documents (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    claim_id          TEXT NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    file_id           TEXT NOT NULL,
    file_name         TEXT,
    actual_type       TEXT NOT NULL,
    quality           TEXT NOT NULL DEFAULT 'GOOD',
    patient_name_on_doc TEXT,
    file_path         TEXT,
    content_json      TEXT,          -- DocumentContent as JSON (may be NULL)
    created_at        TEXT NOT NULL
);
"""


# ── Connection helper ─────────────────────────────────────────────────────────

def _get_conn() -> sqlite3.Connection:
    """Return a connection with WAL mode and row-factory for dict-like rows."""
    DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """Create tables if they don't exist yet. Call once at startup."""
    with _get_conn() as conn:
        conn.executescript(_DDL)
    print(f"[DB] Initialized SQLite database at {DB_PATH}")


# ── Write operations ──────────────────────────────────────────────────────────

def save_claim(claim_data: dict[str, Any], result: dict[str, Any]) -> None:
    """
    Persist a processed claim and its documents.

    Parameters
    ----------
    claim_data : dict
        Output of ClaimSubmission.model_dump()
    result : dict
        Output of process_claim() — the full pipeline result
    """
    claim_id = claim_data["claim_id"]
    submitted_at = datetime.utcnow().isoformat()

    # Extract top-level decision fields if present
    decision = result.get("decision")
    approved_amount = result.get("approved_amount")
    confidence_score = result.get("confidence_score")

    with _get_conn() as conn:
        # Upsert the claim row (replace on re-submit with same id)
        conn.execute(
            """
            INSERT OR REPLACE INTO claims
                (claim_id, member_id, policy_id, claim_category, treatment_date,
                 claimed_amount, hospital_name, ytd_claims_amount,
                 decision, approved_amount, confidence_score,
                 submitted_at, result_json, claim_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                claim_id,
                claim_data.get("member_id", ""),
                claim_data.get("policy_id", "PLUM_GHI_2024"),
                str(claim_data.get("claim_category", "")),
                str(claim_data.get("treatment_date", "")),
                float(claim_data.get("claimed_amount", 0)),
                claim_data.get("hospital_name"),
                float(claim_data.get("ytd_claims_amount", 0)),
                str(decision) if decision else None,
                float(approved_amount) if approved_amount is not None else None,
                float(confidence_score) if confidence_score is not None else None,
                submitted_at,
                json.dumps(result, default=str),
                json.dumps(claim_data, default=str),
            ),
        )

        # Delete old document rows for this claim before re-inserting
        conn.execute("DELETE FROM documents WHERE claim_id = ?", (claim_id,))

        # Insert one row per document
        for doc in claim_data.get("documents", []):
            content = doc.get("content")
            conn.execute(
                """
                INSERT INTO documents
                    (claim_id, file_id, file_name, actual_type, quality,
                     patient_name_on_doc, file_path, content_json, created_at)
                VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    claim_id,
                    doc.get("file_id", ""),
                    doc.get("file_name"),
                    str(doc.get("actual_type", "")),
                    str(doc.get("quality", "GOOD")),
                    doc.get("patient_name_on_doc"),
                    doc.get("file_path"),
                    json.dumps(content, default=str) if content else None,
                    submitted_at,
                ),
            )


# ── Read operations ───────────────────────────────────────────────────────────

def get_all_claims() -> list[dict[str, Any]]:
    """Return summary rows for every claim (no full JSON blobs)."""
    with _get_conn() as conn:
        rows = conn.execute(
            """
            SELECT claim_id, member_id, claim_category, claimed_amount,
                   decision, approved_amount, confidence_score, submitted_at
            FROM claims
            ORDER BY submitted_at DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


def get_claim(claim_id: str) -> dict[str, Any] | None:
    """Return the full claim row including parsed result and claim JSON."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM claims WHERE claim_id = ?", (claim_id,)
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        # Parse JSON blobs back into dicts
        data["result"] = json.loads(data.pop("result_json") or "{}")
        data["claim"] = json.loads(data.pop("claim_json") or "{}")

        # Attach document rows
        doc_rows = conn.execute(
            "SELECT * FROM documents WHERE claim_id = ? ORDER BY id", (claim_id,)
        ).fetchall()
        docs = []
        for dr in doc_rows:
            d = dict(dr)
            d["content"] = json.loads(d.pop("content_json") or "null")
            docs.append(d)
        data["documents"] = docs

    return data


def get_documents_for_claim(claim_id: str) -> list[dict[str, Any]]:
    """Return all document rows for a given claim."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM documents WHERE claim_id = ? ORDER BY id", (claim_id,)
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["content"] = json.loads(d.pop("content_json") or "null")
        result.append(d)
    return result
