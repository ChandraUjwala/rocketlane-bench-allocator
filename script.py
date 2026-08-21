import os
import requests
from datetime import datetime, timedelta

API_KEY = os.environ.get("ROCKETLANE_API_KEY")
RMG_PROJECT_ID = os.environ.get("RMG_PROJECT_ID")
BASE_URL = "https://api.rocketlane.com/api/1.0"

headers = {
    "accept": "application/json",
    "api-key": API_KEY,
    "content-type": "application/json"
}

# Date parameters required by Rocketlane
today_str = datetime.now().strftime("%Y-%m-%d")
tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
bench_end_str = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

# 1. Fetch allocations ending today
params = {
    "startDate": today_str,
    "endDate": today_str,
    "pageSize": 100
}

res = requests.get(f"{BASE_URL}/resource-allocations", headers=headers, params=params)

if res.status_code != 200:
    print(f"Error fetching allocations: {res.status_code} - {res.text}")
    exit(1)

allocations = res.json().get("data", [])
users_to_bench = set()

# 2. Extract users whose allocations end today and aren't already on RMG
for alloc in allocations:
    # Safely retrieve Project ID
    proj_id = alloc.get("projectId")
    if isinstance(alloc.get("project"), dict):
        proj_id = alloc.get("project").get("id") or proj_id

    # Safely retrieve User ID
    user_id = alloc.get("userId") or alloc.get("memberId")
    
    alloc_for = alloc.get("allocationFor")
    if isinstance(alloc_for, dict):
        user_id = alloc_for.get("member", {}).get("id") or alloc_for.get("id") or user_id

    # Filter out RMG project allocations and aggregate valid users
    if proj_id != RMG_PROJECT_ID and user_id:
        users_to_bench.add(user_id)

print(f"Found {len(users_to_bench)} user(s) ending project allocations today.")

# 3. Build bulk payload to allocate users to the RMG project starting tomorrow
create_payload = []
for user_id in users_to_bench:
    create_payload.append({
        "type": "user",
        "userId": user_id,
        "projectId": RMG_PROJECT_ID,
        "startDate": tomorrow_str,
        "endDate": bench_end_str,
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
    print("No resources ending project allocations today.")
