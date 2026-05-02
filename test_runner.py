import requests, json
with open("test_cases.json") as f:
    tcs = json.load(f)["test_cases"]

for i, tc in enumerate(tcs):
    r = requests.post("http://localhost:8000/api/claims/test", json=tc["input"])
    print(f"TC {i+1} status: {r.status_code}")
    if r.status_code != 200:
        print(r.text)
