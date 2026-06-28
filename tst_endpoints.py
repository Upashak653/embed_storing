import requests

BASE = "http://localhost:8000"

print("=== ENDPOINT HEALTH CHECK ===\n")

# Test 1: Search
print("--- /search ---")
r = requests.post(f"{BASE}/search", json={"query": "sales order", "top_k": 5, "min_score": 0.0})
if r.status_code == 200:
    results = r.json().get("results", [])
    print(f"✅ /search OK — {len(results)} results")
    for x in results:
        print(f"   {round(x['score'],3):<6} {x['route']:<15} {x['api_name']}")
else:
    print(f"❌ /search FAILED — status {r.status_code}")

print()

# Test 2: Feedback
print("--- /feedback ---")
results = requests.post(f"{BASE}/search", json={"query":"billing","top_k":1,"min_score":0.0}).json().get("results",[])
if results:
    chunk_id = results[0]["id"]
    fb = requests.post(f"{BASE}/feedback", json={"chunk_id": chunk_id, "vote": "up", "query": "billing"})
    if fb.status_code == 200:
        print(f"✅ /feedback OK — {fb.json()}")
    else:
        print(f"❌ /feedback FAILED — status {fb.status_code}")
else:
    print("❌ No results to test feedback")

print()

# Test 3: Score distribution check
print("--- SCORE DISTRIBUTION ---")
for q in ["billing document", "sales order", "purchase order", "business partner"]:
    r = requests.post(f"{BASE}/search", json={"query": q, "top_k": 3, "min_score": 0.0})
    results = r.json().get("results", [])
    if results:
        top = results[0]
        gap = round(results[0]["score"] - results[1]["score"], 3) if len(results) > 1 else "N/A"
        print(f"  {q:<22} top={round(top['score'],3)} gap={gap} api={top['api_name']}")