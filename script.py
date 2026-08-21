import os
import sys
import requests
from datetime import datetime, timedelta

# ==================== CONFIGURATION ====================
API_KEY = os.environ.get("ROCKETLANE_API_KEY")
RMG_PROJECT_ID = os.environ.get("RMG_PROJECT_ID", "1427884")  # Bench allocation project (fixed)

BASE_URL = "https://api.rocketlane.com/api/1.0"
BULK_ACTION_URL = "https://api.rocketlane.com/api/v1/resource-allocations/bulk-action"
NOT_PART_OF_PROJECT_ERROR = "RM_USER_NOT_PART_OF_PROJECT"
REQUEST_TIMEOUT = 30

if not API_KEY:
    print("ERROR: ROCKETLANE_API_KEY environment variable is not set.")
    sys.exit(1)

headers = {
    "accept": "application/json",
    "content-type": "application/json",
    "api-key": API_KEY,
    "x-api-key": API_KEY
}

# --- DATE LOGIC ---
today = datetime.now()
target_end_date = today.strftime("%Y-%m-%d")

# Start on the Monday immediately following today
days_to_monday = (7 - today.weekday()) % 7
if days_to_monday == 0:
    days_to_monday = 1  # Next Monday if today is Sunday
bench_start_dt = today + timedelta(days=days_to_monday)
bench_start_date = bench_start_dt.strftime("%Y-%m-%d")

# 4 full weeks ending on Sunday
bench_end_dt = bench_start_dt + timedelta(days=27)
bench_end_date = bench_end_dt.strftime("%Y-%m-%d")

print(f"Targeting Allocations Ending On : {target_end_date}")
print(f"Bench Allocation Range         : {bench_start_date} to {bench_end_date} (Mon -> Sun)\n")

# ---------------------------------------------------------
# Step 1: Fetch allocations ending today
# ---------------------------------------------------------
allocations = []
next_page_token = None
page_count = 1

print("Fetching ending allocations from Rocketlane...")

while True:
    params = {
        "startDate": target_end_date,
        "endDate": target_end_date,
        "includeFields": "member",
        "pageSize": 100
    }
    if next_page_token:
        params["pageToken"] = next_page_token

    res = requests.get(f"{BASE_URL}/resource-allocations", headers=headers, params=params, timeout=REQUEST_TIMEOUT)

    if res.status_code != 200:
        print(f"API Error ({res.status_code}): {res.text}")
        sys.exit(1)

    res_json = res.json()
    page_data = res_json.get("data", [])
    allocations.extend(page_data)

    pagination_info = res_json.get("pagination", {}) or res_json.get("meta", {})
    next_page_token = pagination_info.get("nextPageToken") or pagination_info.get("pageToken")

    if not next_page_token or len(page_data) == 0:
        break
    page_count += 1

print(f"Total records fetched across {page_count} page(s): {len(allocations)}\n")

users_to_bench = set()
member_details = {}  # userId (str) -> {emailId, firstName, lastName}, needed for the add-members fallback

for alloc in allocations:
    end_date = alloc.get("endDate")
    proj_info = alloc.get("project") if isinstance(alloc.get("project"), dict) else {}
    proj_id = proj_info.get("projectId")

    # "member" is the actual resource the allocation is assigned to (only present
    # because we requested includeFields=member). createdBy/updatedBy are audit
    # fields for who created/edited the record, not who it's assigned to.
    member_info = alloc.get("member") if isinstance(alloc.get("member"), dict) else {}
    user_id = member_info.get("userId")

    if user_id and str(proj_id) != str(RMG_PROJECT_ID) and end_date == target_end_date:
        users_to_bench.add(str(user_id))
        member_details[str(user_id)] = {
            "emailId": member_info.get("emailId"),
            "firstName": member_info.get("firstName"),
            "lastName": member_info.get("lastName"),
        }
        print(f"-> Found candidate User ID {user_id} ending allocation on project {proj_id}")

print(f"\nUsers Ending Allocations Today: {users_to_bench}\n")

# ---------------------------------------------------------
# Step 2: Deduplicate against existing Bench Project allocations
# ---------------------------------------------------------
final_users_to_bench = set()

if users_to_bench:
    print("Checking existing allocations on RMG Bench Project...")

    already_benched_users = set()
    rmg_next_page_token = None

    while True:
        rmg_params = {
            "startDate": bench_start_date,
            "endDate": bench_end_date,
            "projectId.eq": RMG_PROJECT_ID,
            "memberId.oneOf": ",".join(users_to_bench),
            "includeFields": "member",
            "pageSize": 100
        }
        if rmg_next_page_token:
            rmg_params["pageToken"] = rmg_next_page_token

        rmg_res = requests.get(f"{BASE_URL}/resource-allocations", headers=headers, params=rmg_params, timeout=REQUEST_TIMEOUT)
        if rmg_res.status_code != 200:
            print(f"API Error checking existing bench allocations ({rmg_res.status_code}): {rmg_res.text}")
            sys.exit(1)

        rmg_json = rmg_res.json()
        rmg_allocs = rmg_json.get("data", [])

        for alloc in rmg_allocs:
            m_info = alloc.get("member") if isinstance(alloc.get("member"), dict) else {}
            existing_uid = m_info.get("userId")
            if existing_uid:
                already_benched_users.add(str(existing_uid))

        rmg_pagination_info = rmg_json.get("pagination", {}) or rmg_json.get("meta", {})
        rmg_next_page_token = rmg_pagination_info.get("nextPageToken") or rmg_pagination_info.get("pageToken")

        if not rmg_next_page_token or len(rmg_allocs) == 0:
            break

    for uid in users_to_bench:
        if uid in already_benched_users:
            print(f"--> User ID {uid} already has an active allocation on Bench Project ({RMG_PROJECT_ID}) for {bench_start_date} to {bench_end_date}. Skipping.")
        else:
            final_users_to_bench.add(uid)

print(f"\nFinal Users Queued for Bench: {final_users_to_bench}\n")

# ---------------------------------------------------------
# Step 3: Create Bulk Allocations
# ---------------------------------------------------------
if final_users_to_bench:
    create_payload = []
    for uid in final_users_to_bench:
        create_payload.append({
            "type": "user",
            "userId": int(uid),
            "projectId": RMG_PROJECT_ID,
            "startDate": bench_start_date,
            "endDate": bench_end_date,
            "minutes": 480,  # 8 hours/day
            "billable": False,
            "medium": "HARD",
            "addToProject": True,
            "fields": [
                {
                    "fieldId": 2630216,  # Resource Type custom field
                    "fieldValue": 1
                }
            ]
        })

    print("Submitting Bulk Allocation to RMG Bench Project...")
    bulk_res = requests.post(
        BULK_ACTION_URL,
        headers=headers,
        json={"create": create_payload, "update": [], "delete": []},
        timeout=REQUEST_TIMEOUT
    )
    print(f"HTTP Status: {bulk_res.status_code}")
    print(f"Response Body: {bulk_res.text}")

    # ---------------------------------------------------------
    # Step 4: Fallback for users addToProject couldn't auto-add
    # ---------------------------------------------------------
    # The bulk-action response's "allocations" list mirrors the "create" list
    # positionally, so we match results back to create_payload by index.
    try:
        bulk_results = bulk_res.json().get("allocations", [])
    except ValueError:
        bulk_results = []

    retry_payload = []
    retry_uids = []

    for idx, result in enumerate(bulk_results):
        if idx >= len(create_payload):
            break
        if result.get("status") is False and result.get("errorCode") == NOT_PART_OF_PROJECT_ERROR:
            uid = str(create_payload[idx]["userId"])
            info = member_details.get(uid, {})
            print(f"--> User ID {uid} not part of project {RMG_PROJECT_ID}; adding as member and retrying...")

            add_res = requests.post(
                f"{BASE_URL}/projects/{RMG_PROJECT_ID}/add-members",
                headers=headers,
                json={"members": [{
                    "userId": int(uid),
                    "emailId": info.get("emailId"),
                    "firstName": info.get("firstName"),
                    "lastName": info.get("lastName"),
                }]},
                timeout=REQUEST_TIMEOUT
            )

            if add_res.status_code in (200, 201):
                retry_payload.append(create_payload[idx])
                retry_uids.append(uid)
            else:
                print(f"    Failed to add User ID {uid} to project {RMG_PROJECT_ID}: {add_res.status_code} - {add_res.text}")

    if retry_payload:
        print(f"Retrying bench allocation for: {retry_uids}")
        retry_res = requests.post(
            BULK_ACTION_URL,
            headers=headers,
            json={"create": retry_payload, "update": [], "delete": []},
            timeout=REQUEST_TIMEOUT
        )
        print(f"Retry HTTP Status: {retry_res.status_code}")
        print(f"Retry Response Body: {retry_res.text}")
else:
    print("No new resources to allocate (all candidate resources already benched).")
