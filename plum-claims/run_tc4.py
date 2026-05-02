import sys, os, json, asyncio
sys.path.append(os.path.join(os.getcwd(), 'backend'))
from backend.agents.graph import build_claims_pipeline
from backend.models.claim import ClaimSubmission
from backend.main import DocumentUpload, DocumentType, DocumentQuality, DocumentContent

with open("../test_cases.json") as f:
    tcs = json.load(f)["test_cases"]

tc = tcs[3]["input"] # TC 4
docs = []
for d in tc["documents"]:
    docs.append(DocumentUpload(
        file_id=d["file_id"],
        file_name=d.get("file_name"),
        actual_type=DocumentType(d["actual_type"]),
        quality=DocumentQuality(d.get("quality", "GOOD")),
        content=DocumentContent(**d["content"]) if "content" in d else None,
    ))
claim = ClaimSubmission(
    member_id=tc["member_id"],
    policy_id=tc["policy_id"],
    claim_category=tc["claim_category"],
    treatment_date=tc["treatment_date"],
    claimed_amount=tc["claimed_amount"],
    documents=docs,
)
state = {"claim": claim.model_dump()}
app = build_claims_pipeline().compile()

def run():
    print("Running TC4...")
    for step in app.stream(state):
        print(list(step.keys()))
    print("Done")
run()
