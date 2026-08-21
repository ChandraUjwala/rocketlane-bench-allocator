import os
import requests

API_KEY = os.environ.get("ROCKETLANE_API_KEY")
RMG_PROJECT_ID = os.environ.get("RMG_PROJECT_ID")
BASE_URL = "https://api.rocketlane.com/api/1.0"

headers = {
    "accept": "application/json",
    "api-key": API_KEY,
    "content-type": "application/json"
}

# --- TEST OVERRIDES ---
target_end_date = "2026-08-23"    # Matches your test resource's allocation end date
bench_start_date = "2026-08-24"   # Bench allocation starts the next day
bench_end_date = "2026-09-24"     # 30-day bench duration
# ----------------------

params = {
    "startDate": target_end_date,
    "endDate": target_end_date,
    "pageSize": 100
}

res = requests.get(f"{BASE_URL}/resource-allocations", headers=headers, params=params)

if res.status_code != 200:
    print(f"Error fetching allocations: {res.status_code} - {res.text}")
    exit(1)

allocations = res.json().get("data", [])
users_to_bench = set()

# Extract users whose allocations end on the test date and aren't on RMG
for alloc in allocations:
    proj_id = alloc.get("projectId")
    if isinstance(alloc.get("project"), dict):
        proj_id = alloc.get("project").get("id") or proj_id

    user_id = alloc.get("userId") or alloc.get("memberId")
    alloc_for = alloc.get("allocationFor")
    if isinstance(alloc_for, dict):
        user_id = alloc_for.get("member", {}).get("id") or alloc_for.get("id") or user_id

    if proj_id != RMG_PROJECT_ID and user_id:
        users_to_bench.add(user_id)

print(f"Found {len(users_to_bench)} user(s) ending allocations on {target_end_date}.")

create_payload = []
for user_id in users_to_bench:
    create_payload.append({
        "type": "user",
        "userId": user_id,
        "projectId": RMG_PROJECT_ID,
        "startDate": bench_start_date,
        "endDate": bench_end_date,
        "minutes": 480,  # 8 hours/day
        "billable": False,
        "medium": "HARD"
    })

if create_payload:
    bulk_res = requests.post(
        "https://api.rocketlane.com/api/v1/resource-allocations/bulk-action",
        headers=headers,
        json={"create": create_payload, "update": [], "delete": []}
    )
    print(f"Bench allocation HTTP status: {bulk_res.status_code}")
    print(f"Response: {bulk_res.text}")
else:
    print("No resources matching the test criteria.")
