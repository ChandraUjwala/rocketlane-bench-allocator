import os
import sys
import requests


def env_or_default(name, default):
    # os.environ.get's default only kicks in when the key is absent -- but a
    # GitHub Actions secret that isn't configured still sets the env var to an
    # empty string, so an empty value needs to fall back too.
    return os.environ.get(name) or default


# ==================== CONFIGURATION ====================
API_KEY = os.environ.get("ROCKETLANE_API_KEY")
ACTUAL_MARGIN_FIELD_ID = int(env_or_default("ACTUAL_MARGIN_FIELD_ID", "2630597"))
ESTIMATED_MARGIN_FIELD_ID = int(env_or_default("ESTIMATED_MARGIN_FIELD_ID", "2630596"))

BASE_URL = "https://api.rocketlane.com/api/1.0"
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

# ---------------------------------------------------------
# Step 1: Fetch all active projects, with margin metrics included
# ---------------------------------------------------------
projects = []
next_page_token = None
page_count = 1

print("Fetching projects from Rocketlane...")

while True:
    params = {
        "includeFields": "metrics",
        "pageSize": 100
    }
    if next_page_token:
        params["pageToken"] = next_page_token

    res = requests.get(f"{BASE_URL}/projects", headers=headers, params=params, timeout=REQUEST_TIMEOUT)

    if res.status_code != 200:
        print(f"API Error fetching projects ({res.status_code}): {res.text}")
        sys.exit(1)

    res_json = res.json()
    page_data = res_json.get("data", [])
    projects.extend(page_data)

    pagination_info = res_json.get("pagination", {}) or res_json.get("meta", {})
    next_page_token = pagination_info.get("nextPageToken") or pagination_info.get("pageToken")

    if not next_page_token or len(page_data) == 0:
        break
    page_count += 1

print(f"Total projects fetched across {page_count} page(s): {len(projects)}\n")

# ---------------------------------------------------------
# Step 2: Push actual/estimated margin into the custom fields
# ---------------------------------------------------------
updated_count = 0
skipped_count = 0
failed_count = 0

for project in projects:
    if project.get("archived"):
        skipped_count += 1
        continue

    project_id = project.get("projectId")
    metrics = project.get("metrics") if isinstance(project.get("metrics"), dict) else {}

    actual_margin = metrics.get("actualProfitMargin")
    estimated_margin = metrics.get("estimatedProfitMargin")

    if actual_margin is None or estimated_margin is None:
        print(f"-> Project {project_id}: no margin metrics available, skipping.")
        skipped_count += 1
        continue

    update_res = requests.put(
        f"{BASE_URL}/projects/{project_id}",
        headers=headers,
        json={
            "fields": [
                {"fieldId": ACTUAL_MARGIN_FIELD_ID, "fieldValue": actual_margin},
                {"fieldId": ESTIMATED_MARGIN_FIELD_ID, "fieldValue": estimated_margin}
            ]
        },
        timeout=REQUEST_TIMEOUT
    )

    if update_res.status_code == 200:
        print(f"-> Project {project_id}: synced (actual={actual_margin:.2f}%, estimated={estimated_margin:.2f}%)")
        updated_count += 1
    else:
        print(f"-> Project {project_id}: FAILED ({update_res.status_code}) - {update_res.text}")
        failed_count += 1

print(f"\nDone. Updated: {updated_count}, Skipped: {skipped_count}, Failed: {failed_count}")
