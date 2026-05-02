import sys, os
sys.path.append(os.path.join(os.getcwd(), 'backend'))

import json, asyncio
from backend.agents.graph import process_claim
from backend.models.claim import ClaimSubmission
from backend.main import DocumentUpload, DocumentType, DocumentQuality

with open("../test_cases.json") as f:
    tcs = json.load(f)["test_cases"]

tc = tcs[0]["input"]
docs = []
for d in tc["documents"]:
    docs.append(DocumentUpload(
        file_id=d["file_id"],
        file_name=d["file_name"],
        actual_type=DocumentType(d["actual_type"]),
        quality=DocumentQuality(d.get("quality", "GOOD")),
    ))

claim = ClaimSubmission(
    member_id=tc["member_id"],
    policy_id=tc["policy_id"],
    claim_category=tc["claim_category"],
    treatment_date=tc["treatment_date"],
    claimed_amount=tc["claimed_amount"],
    documents=docs,
)
try:
    print(process_claim(claim))
except Exception as e:
    import traceback
    traceback.print_exc()
