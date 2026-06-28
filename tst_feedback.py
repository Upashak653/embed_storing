import requests

BASE = "http://localhost:8000"

print("=== FEEDBACK LOOP TEST ===")

# First search to get a chunk_id
r = requests.post(f"{BASE}/search", json={"query": "billing document", "top_k": 3, "min_score": 0.0})
results = r.json().get("results", [])

if not results:
    print("❌ No search results — backend may be down")
    exit()

chunk_id = results[0]["id"]
api_name = results[0]["api_name"]
score_before = results[0]["score"]
print(f"Top result: {api_name} | chunk_id={chunk_id} | score={score_before}")

# Send upvote
print("\nSending upvote...")
fb = requests.post(f"{BASE}/feedback", json={"chunk_id": chunk_id, "vote": "up", "query": "billing document"})
print(f"Feedback response: {fb.json()}")

# Send downvote on second result
if len(results) > 1:
    chunk_id2 = results[1]["id"]
    api_name2 = results[1]["api_name"]
    print(f"\nSending downvote on: {api_name2} | chunk_id={chunk_id2}")
    fb2 = requests.post(f"{BASE}/feedback", json={"chunk_id": chunk_id2, "vote": "down", "query": "billing document"})
    print(f"Feedback response: {fb2.json()}")

print("\n✅ Feedback loop working" if fb.status_code == 200 else "\n❌ Feedback failed")