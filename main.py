from fastapi import FastAPI, Request, HTTPException, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
import uvicorn
import requests
import pandas as pd
from io import BytesIO
import time
import logging
from urllib.parse import urlparse
import os
import sys
from dotenv import load_dotenv
import json
from concurrent.futures import ThreadPoolExecutor, as_completed

def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and for PyInstaller"""
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.abspath(relative_path)

# Load environment variables from the app directory
load_dotenv(get_resource_path("app/.env"))

# Setup Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

app = FastAPI()

# Token Cache
TOKEN_CACHE = {
    "access_token": None,
    "expires_at": 0,
    "auth_url": None,
    "base_url": None,
    "password": None,
}

# Slot duration constant: 1 slot = 5 minutes
SLOT_DURATION_MINUTES = 5

app.mount("/static", StaticFiles(directory=get_resource_path("app/static")), name="static")
templates = Jinja2Templates(directory=get_resource_path("app/templates"))

# --- Pydantic Models ---

class BaseFetchRequest(BaseModel):
    base_url: str
    password: Optional[str] = ""

class FetchDetailsRequest(BaseFetchRequest):
    selected_location_ids: List[int]

class FetchAllDataRequest(BaseFetchRequest):
    selected_location_ids: List[int]

class FetchUserDetailRequest(BaseFetchRequest):
    user_detail_id: str | int


class SaveConfigRequest(BaseModel):
    locations: List[Any]
    providers: List[Any]
    productionTypes: Dict[int, List[int]]
    excludedInsurance: str
    notes: str
    botEnabled: bool
    full_locations: List[Dict[str, Any]]
    full_providers: List[Dict[str, Any]]
    full_production_types: List[Dict[str, Any]]


# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "v": int(time.time()),
            "carestack_api_url": os.getenv("CARESTACK_API_URL", ""),
            "carestack_password": os.getenv("CARESTACK_PASSWORD", "")
        }
    )


# --- Auth ---

def get_carestack_token(creds: BaseFetchRequest):
    """Authenticate with Carestack OAuth and return an access token (cached for 2.5h)."""
    auth_base_url = os.getenv("CARESTACK_AUTH_URL", "").rstrip("/")
    username = os.getenv("CARESTACK_USERNAME", "")
    client_id = os.getenv("CARESTACK_CLIENT_ID", "")
    client_secret = os.getenv("CARESTACK_CLIENT_SECRET", "")

    if not auth_base_url or not username or not client_id or not client_secret:
        raise HTTPException(
            status_code=500,
            detail="Server auth credentials not configured. Check CARESTACK_AUTH_URL, CARESTACK_USERNAME, CARESTACK_CLIENT_ID, CARESTACK_CLIENT_SECRET env vars."
        )

    auth_url = f"{auth_base_url}/connect/token"
    token = None

    global TOKEN_CACHE
    now = time.time()

    # Check if we have a valid cached token for the same auth URL, base URL, and password
    if (TOKEN_CACHE["access_token"] and
        now < TOKEN_CACHE["expires_at"] and
        TOKEN_CACHE.get("auth_url") == auth_url and
        TOKEN_CACHE.get("base_url") == creds.base_url and
        TOKEN_CACHE.get("password") == creds.password):
        token = TOKEN_CACHE["access_token"]

    if not token:
        payload = {
            "grant_type": "password",
            "client_id": client_id,
            "client_secret": client_secret,
            "username": username,
            "password": creds.password
        }

        auth_resp = requests.post(auth_url, data=payload, timeout=30)

        if auth_resp.status_code == 200:
            token = auth_resp.json().get("access_token")
            TOKEN_CACHE["access_token"] = token
            TOKEN_CACHE["expires_at"] = now + (2.5 * 3600)
            TOKEN_CACHE["auth_url"] = auth_url
            TOKEN_CACHE["base_url"] = creds.base_url
            TOKEN_CACHE["password"] = creds.password
        else:
            logger.error(f"Authentication failed: {auth_resp.status_code} - {auth_resp.text}")
            raise HTTPException(status_code=400, detail=f"Authentication failed: {auth_resp.text}")

    if not token:
        logger.error("Could not retrieve access token")
        raise HTTPException(status_code=400, detail="Could not retrieve access token")

    return token


# --- Fetch Locations ---

@app.post("/api/fetch-locations")
def fetch_locations(creds: BaseFetchRequest):
    try:
        token = get_carestack_token(creds)
        api_base_url = creds.base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {token}"}

        loc_resp = requests.get(f"{api_base_url}/api/v1.0/locations", headers=headers, timeout=30)
        loc_resp.raise_for_status()
        raw_locations = loc_resp.json()

        locations = []
        for l in raw_locations:
            addr = l.get("address", {})
            address_str = f"{addr.get('addressLine1', '')} {addr.get('city', '')}, {addr.get('state', '')}"
            locations.append({
                "id": l.get("id"),
                "name": l.get("name") or l.get("shortName"),
                "address": address_str,
                "phone": l.get("phone1") or "N/A"
            })

        return {"locations": locations}

    except requests.RequestException as e:
        error_msg = str(e)
        if getattr(e, 'response', None) is not None:
            logger.error(f"API Error Response: {e.response.text}")
            error_msg += f" | Response: {e.response.text}"
        logger.error(f"API Request failed: {error_msg}")
        raise HTTPException(status_code=400, detail=f"API Request failed: {error_msg}")
    except Exception as e:
        logger.exception("Internal Error during fetch_locations")
        raise HTTPException(status_code=500, detail=f"Internal Error: {str(e)}")


# --- Fetch All Data (Consolidated) ---

@app.post("/api/fetch-all-data")
def fetch_all_data(creds: FetchAllDataRequest):
    """
    Consolidated endpoint that fetches providers, production types,
    operatories, users, and scheduler production types in parallel.
    Merges scheduler PT data (slotLength, providerSpecialities) with main PT data.
    """
    try:
        token = get_carestack_token(creds)
        api_base_url = creds.base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {token}"}

        # Build scheduler URL
        parsed = urlparse(creds.base_url)
        domain_parts = parsed.netloc.split('.')
        subdomain = domain_parts[0] if domain_parts else "api"
        if not parsed.scheme and not parsed.netloc:
            subdomain = "api"
        scheduler_base = f"https://{subdomain}.services.carestack.com/scheduler/api/v1.0"

        location_params = [('locationId', lid) for lid in creds.selected_location_ids]

        results = {}

        def _fetch_providers():
            resp = requests.get(
                f"{api_base_url}/api/v1.0/providers",
                headers=headers, params=location_params, timeout=30
            )
            resp.raise_for_status()
            return resp.json()

        def _fetch_production_types():
            resp = requests.get(
                f"{api_base_url}/api/v1.0/production-types",
                headers=headers, params=location_params, timeout=30
            )
            resp.raise_for_status()
            return resp.json()

        def _fetch_operatories():
            resp = requests.get(
                f"{api_base_url}/api/v1.0/operatories",
                headers=headers, timeout=30
            )
            resp.raise_for_status()
            return resp.json()

        def _fetch_scheduler_pts():
            resp = requests.get(
                f"{scheduler_base}/production-types",
                headers=headers, params=location_params, timeout=30
            )
            resp.raise_for_status()
            return resp.json()

        def _fetch_operatory_providers():
            resp = requests.get(
                f"{scheduler_base}/provider-availability/operatory-provider",
                headers=headers, timeout=30
            )
            resp.raise_for_status()
            return resp.json()

        def _fetch_calendar_templates():
            resp = requests.get(
                f"{scheduler_base}/production-calender/template",
                headers=headers, params=location_params, timeout=30
            )
            resp.raise_for_status()
            return resp.json()
            
        def _fetch_provider_availability_templates():
            resp = requests.get(
                f"{scheduler_base}/provider-availability/template",
                headers=headers, params=location_params, timeout=30
            )
            resp.raise_for_status()
            return resp.json()

        def _fetch_all_providers():
            """Fetch ALL providers (no location filter) for name resolution."""
            resp = requests.get(
                f"{api_base_url}/api/v1.0/providers",
                headers=headers, timeout=30
            )
            resp.raise_for_status()
            return resp.json()

        def _fetch_users():
            url = f"{api_base_url}/setup/user/grid-get-users-all"
            payload = {
                "PageIndex": 1,
                "PageSize": 1000,
                "OrderBy": "UserDetailID desc",
                "FilterQuery": {"IsActive": True}
            }
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
            if resp.status_code == 404:
                resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            users_list = []
            if isinstance(data, list):
                users_list = data
            elif isinstance(data, dict):
                if "Result" in data and isinstance(data["Result"], list):
                    users_list = data["Result"]
                elif "Items" in data and isinstance(data["Items"], list):
                    users_list = data["Items"]
                elif "items" in data and isinstance(data["items"], list):
                    users_list = data["items"]

            # Filter to users with a ProviderID
            filtered = []
            for u in users_list:
                pid = u.get("ProviderID")
                if pid is not None and str(pid).lower() != "null":
                    # Fetch detail for MaxConcurrentAppointments
                    try:
                        detail_url = f"{api_base_url}/setup/user/get/{u.get('UserDetailID')}"
                        detail_resp = requests.get(detail_url, headers=headers, timeout=10)
                        if detail_resp.status_code == 200:
                            detail_data = detail_resp.json()
                            provider_info = detail_data.get("Provider", {})
                            u["MaxConcurrentAppointments"] = provider_info.get("MaxConcurrentAppointments", "N/A")
                        else:
                            u["MaxConcurrentAppointments"] = "N/A"
                    except Exception:
                        u["MaxConcurrentAppointments"] = "N/A"
                    filtered.append(u)
            return filtered

        # Execute fetches in parallel (users is slow due to N+1, but included)
        with ThreadPoolExecutor(max_workers=8) as executor:
            future_providers = executor.submit(_fetch_providers)
            future_all_providers = executor.submit(_fetch_all_providers)
            future_pts = executor.submit(_fetch_production_types)
            future_ops = executor.submit(_fetch_operatories)
            future_sched = executor.submit(_fetch_scheduler_pts)
            future_users = executor.submit(_fetch_users)
            future_op_prov = executor.submit(_fetch_operatory_providers)
            future_templates = executor.submit(_fetch_calendar_templates)
            future_prov_avail_templates = executor.submit(_fetch_provider_availability_templates)

            raw_providers = future_providers.result()
            raw_all_providers = future_all_providers.result()
            raw_pts = future_pts.result()
            raw_ops = future_ops.result()
            raw_sched_pts = future_sched.result()
            raw_users = future_users.result()
            raw_op_prov = future_op_prov.result()
            raw_templates = future_templates.result()
            raw_prov_avail_templates = future_prov_avail_templates.result()


        # --- Build Operatory -> Production Types map ---
        operatory_production_types = {}
        for template in raw_templates:
            pt_id_str = template.get("productionTypeId")
            if pt_id_str and isinstance(pt_id_str, str):
                try:
                    pt_map = json.loads(pt_id_str)
                    for op_id, pt_list in pt_map.items():
                        if op_id not in operatory_production_types:
                            operatory_production_types[op_id] = set()
                        for pt in pt_list:
                            operatory_production_types[op_id].add(pt)
                except json.JSONDecodeError:
                    pass
        
        # Convert sets to lists for JSON serialization
        for op_id in operatory_production_types:
            operatory_production_types[op_id] = list(operatory_production_types[op_id])

        # --- Fetch Production Calendar Timestamp Details ---
        # Collect unique rowVersionStamps from templates filtered to selected locations
        day_names_map = {0: "Sun", 1: "Mon", 2: "Tue", 3: "Wed", 4: "Thu", 5: "Fri", 6: "Sat"}
        stamp_to_template_info = {}  # stamp -> { templateName, days }
        day_template_counts = {i: 0 for i in range(7)}  # track number of templates per day (limit 2)
        
        for template in raw_templates:
            if template.get("locationId") not in creds.selected_location_ids:
                continue
            stamp = template.get("rowVersionStamp")
            if not stamp or stamp in stamp_to_template_info:
                continue
            
            recurrences = template.get("templateRecurrence", [])
            unique_days = {r.get("dayOfWeek") for r in recurrences if r.get("dayOfWeek") is not None}
            
            valid_days = []
            for day in unique_days:
                if day_template_counts.get(day, 0) < 2:
                    valid_days.append(day)
                    day_template_counts[day] += 1
            
            if not valid_days:
                continue  # Skip template if all its recurrences exceed the 2-per-day limit
            
            stamp_to_template_info[stamp] = {
                "templateName": template.get("templateName", f"Template #{template.get('templateId')}"),
                "templateId": template.get("templateId"),
                "days": valid_days,
            }

        logger.info(f"Fetching timestamp details for {len(stamp_to_template_info)} unique templates in selected locations")

        # Fetch timestamp detail for each unique stamp
        def _fetch_timestamp_detail(stamp):
            url = f"{scheduler_base}/production-calender/template/timestamp"
            resp = requests.get(url, headers=headers, params={"timestamp": stamp}, timeout=15)
            resp.raise_for_status()
            return stamp, resp.json()

        calendar_pt_durations = {}  # ptId -> { durations: set, templates: set, days: set, time_ranges: list }
        with ThreadPoolExecutor(max_workers=10) as executor:
            timestamp_futures = {
                executor.submit(_fetch_timestamp_detail, stamp): stamp
                for stamp in stamp_to_template_info.keys()
            }
            for future in as_completed(timestamp_futures):
                try:
                    stamp, ts_data = future.result()
                    template_info = stamp_to_template_info[stamp]
                    template_name = template_info["templateName"]
                    template_days = template_info["days"]

                    if isinstance(ts_data, dict):
                        for op_id, slot_ranges in ts_data.items():
                            for slot_range in slot_ranges:
                                if len(slot_range) < 3:
                                    continue
                                start_slot = slot_range[0]
                                end_slot = slot_range[1]
                                pt_id = slot_range[2]
                                duration_mins = (end_slot - start_slot) * SLOT_DURATION_MINUTES

                                start_h, start_m = divmod(start_slot * SLOT_DURATION_MINUTES, 60)
                                end_h, end_m = divmod(end_slot * SLOT_DURATION_MINUTES, 60)
                                time_range = f"{start_h:02d}:{start_m:02d}-{end_h:02d}:{end_m:02d}"

                                if pt_id not in calendar_pt_durations:
                                    calendar_pt_durations[pt_id] = {
                                        "durations": set(),
                                        "templates": set(),
                                        "days": set(),
                                        "time_ranges": [],
                                    }
                                calendar_pt_durations[pt_id]["durations"].add(duration_mins)
                                calendar_pt_durations[pt_id]["templates"].add(template_name)
                                for d in template_days:
                                    calendar_pt_durations[pt_id]["days"].add(d)
                                calendar_pt_durations[pt_id]["time_ranges"].append({
                                    "time": time_range,
                                    "duration": duration_mins,
                                    "template": template_name,
                                    "operatory": op_id,
                                })
                except Exception as e:
                    logger.warning(f"Failed to fetch timestamp detail for stamp: {e}")

        # Convert sets to lists for JSON serialization
        for pt_id in calendar_pt_durations:
            calendar_pt_durations[pt_id]["durations"] = sorted(calendar_pt_durations[pt_id]["durations"])
            calendar_pt_durations[pt_id]["templates"] = sorted(calendar_pt_durations[pt_id]["templates"])
            calendar_pt_durations[pt_id]["days"] = sorted(calendar_pt_durations[pt_id]["days"])
            # Deduplicate time ranges
            seen = set()
            unique_ranges = []
            for tr in calendar_pt_durations[pt_id]["time_ranges"]:
                key = (tr["time"], tr["duration"], tr["template"])
                if key not in seen:
                    seen.add(key)
                    unique_ranges.append(tr)
            calendar_pt_durations[pt_id]["time_ranges"] = unique_ranges

        # Convert ptId keys to strings for JSON serialization
        calendar_pt_durations_str = {str(k): v for k, v in calendar_pt_durations.items()}
        logger.info(f"Computed calendar durations for {len(calendar_pt_durations)} production types")


        # --- Build user concurrency map ---
        user_concurrency_map = {}
        for u in raw_users:
            pid = u.get("ProviderID")
            if pid is not None and str(pid).lower() != "null":
                user_concurrency_map[str(pid)] = u.get("MaxConcurrentAppointments", "N/A")

        # --- Transform Providers ---
        providers = []
        for p in raw_providers:
            p_id = p.get("id")
            providers.append({
                "id": p_id,
                "name": f"{p.get('firstName', '')} {p.get('lastName', '')}".strip(),
                "providerType": p.get("providerType", "Unknown"),
                "specialityId": p.get("specialityId"),
                "color": p.get("color", ""),
                "isActive": p.get("isActive", False),
                "concurrency": user_concurrency_map.get(str(p_id), "N/A"),
            })

        # --- Build complete provider name map from ALL providers (for operatory name resolution) ---
        all_provider_name_map = {}
        for p in raw_all_providers:
            p_id = p.get("id")
            if p_id is not None:
                all_provider_name_map[str(p_id)] = {
                    "name": f"{p.get('firstName', '')} {p.get('lastName', '')}".strip(),
                    "providerType": p.get("providerType", "Unknown"),
                    "isActive": p.get("isActive", False),
                    "concurrency": user_concurrency_map.get(str(p_id), "N/A"),
                }
        logger.info(f"Built all_provider_name_map with {len(all_provider_name_map)} providers (location-filtered: {len(providers)})")

        # --- Build scheduler PT lookup ---
        sched_pt_map = {}
        _logged_sample = False
        for spt in raw_sched_pts:
            allocs = spt.get("providerAllocation", [])

            # Log a sample providerAllocation entry for debugging
            if not _logged_sample and allocs:
                logger.info(f"[DEBUG] Sample providerAllocation entry: {allocs[0]}")
                _logged_sample = True

            specialities = sorted(set(
                a.get("providerSpeciality") for a in allocs
                if a.get("providerSpeciality") is not None
            ))

            # Extract provider IDs from allocation entries
            allocated_provider_ids = sorted(set(
                a.get("providerId") for a in allocs
                if a.get("providerId") is not None
            ))

            slot_length = spt.get("slotLength", 0)
            sched_pt_map[spt.get("id")] = {
                "slotLength": slot_length,
                "durationMinutes": slot_length * SLOT_DURATION_MINUTES,
                "providerSpecialities": specialities,
                "allocatedProviderIds": allocated_provider_ids,
                "isActive": spt.get("isActive", False),
                "locationScope": spt.get("location", {}),
            }

        # --- Transform Production Types (merge with scheduler data) ---
        production_types = []
        for pt in raw_pts:
            pt_id = pt.get("id")
            sched_data = sched_pt_map.get(pt_id, {})

            production_types.append({
                "id": pt_id,
                "name": pt.get("name"),
                "color": pt.get("color", ""),
                "isActive": pt.get("isActive", True),
                "slotLength": sched_data.get("slotLength", 0),
                "durationMinutes": sched_data.get("durationMinutes", 0),
                "providerSpecialities": sched_data.get("providerSpecialities", []),
                "allocatedProviderIds": sched_data.get("allocatedProviderIds", []),
                "locationScope": sched_data.get("locationScope", {}),
            })

        # --- Transform Operatories (filter to selected locations) ---
        operatories = []
        for op in raw_ops:
            if op.get("locationId") in creds.selected_location_ids:
                operatories.append({
                    "id": op.get("id"),
                    "name": op.get("name"),
                    "locationId": op.get("locationId"),
                    "sortOrder": op.get("sortOrder", 0),
                })

        # --- Transform Users ---
        users = []
        for u in raw_users:
            users.append({
                "userDetailId": u.get("UserDetailID") or u.get("Id") or u.get("id"),
                "name": u.get("UserFullName") or u.get("Name") or u.get("name") or
                        f"{u.get('FirstName', '')} {u.get('LastName', '')}".strip(),
                "userName": u.get("UserName") or u.get("userName") or u.get("username"),
                "providerId": u.get("ProviderID"),
                "providerType": u.get("ProviderType", "N/A"),
                "specialtyId": u.get("SpecialtyID"),
                "role": u.get("Role", "N/A"),
                "location": u.get("Location", "N/A"),
                "maxConcurrentAppointments": u.get("MaxConcurrentAppointments", "N/A"),
            })

        return {
            "providers": providers,
            "production_types": production_types,
            "operatories": operatories,
            "users": users,
            "operatory_providers": raw_op_prov,
            "operatory_production_types": operatory_production_types,
            "all_provider_name_map": all_provider_name_map,
            "slot_duration_minutes": SLOT_DURATION_MINUTES,
            "raw_calendar_templates": raw_templates,
            "raw_provider_availability_templates": raw_prov_avail_templates,
            "calendar_pt_durations": calendar_pt_durations_str,
        }

    except requests.RequestException as e:
        error_msg = str(e)
        if getattr(e, 'response', None) is not None:
            logger.error(f"API Error Response: {e.response.text}")
            error_msg += f" | Response: {e.response.text}"
        logger.error(f"API Request failed: {error_msg}")
        raise HTTPException(status_code=400, detail=f"API Request failed: {error_msg}")
    except Exception as e:
        logger.exception("Internal Error during fetch_all_data")
        raise HTTPException(status_code=500, detail=f"Internal Error: {str(e)}")



# --- Probe: Production Calendar Template ---

@app.post("/api/probe-calendar-template")
def probe_calendar_template(creds: FetchAllDataRequest):
    """
    Probe the /scheduler/api/v1.0/production-calender/template endpoint.
    Returns the raw response for inspection.
    """
    try:
        token = get_carestack_token(creds)
        api_base_url = creds.base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {token}"}

        # Build scheduler URL
        parsed = urlparse(creds.base_url)
        domain_parts = parsed.netloc.split('.')
        subdomain = domain_parts[0] if domain_parts else "api"
        if not parsed.scheme and not parsed.netloc:
            subdomain = "api"
        scheduler_base = f"https://{subdomain}.services.carestack.com/scheduler/api/v1.0"

        location_params = [('locationId', lid) for lid in creds.selected_location_ids]

        url = f"{scheduler_base}/production-calender/template"
        logger.info(f"[PROBE] Calling: {url} with params: {location_params}")

        resp = requests.get(url, headers=headers, params=location_params, timeout=30)
        logger.info(f"[PROBE] Status: {resp.status_code}")
        logger.info(f"[PROBE] Response (first 2000 chars): {resp.text[:2000]}")

        resp.raise_for_status()
        data = resp.json()

        # Log structure info
        if isinstance(data, list):
            logger.info(f"[PROBE] Response is a list with {len(data)} items")
            if data:
                logger.info(f"[PROBE] First item keys: {list(data[0].keys()) if isinstance(data[0], dict) else type(data[0])}")
                # Log first 3 items fully
                for i, item in enumerate(data[:3]):
                    logger.info(f"[PROBE] Item {i}: {item}")
        elif isinstance(data, dict):
            logger.info(f"[PROBE] Response is a dict with keys: {list(data.keys())}")

        return {
            "status": resp.status_code,
            "url_called": url,
            "params": dict(location_params),
            "data": data,
        }

    except requests.RequestException as e:
        error_msg = str(e)
        resp_text = ""
        if getattr(e, 'response', None) is not None:
            resp_text = e.response.text
            logger.error(f"[PROBE] API Error Response: {resp_text}")
        return {
            "error": error_msg,
            "response_text": resp_text,
        }
    except Exception as e:
        logger.exception("[PROBE] Internal Error")
        return {"error": str(e)}

@app.get("/api/debug-templates")
def debug_templates(locationId: int):
    try:
        global TOKEN_CACHE
        token = TOKEN_CACHE.get("access_token")
        if not token:
            return {"error": "No cached token"}
        
        headers = {"Authorization": f"Bearer {token}"}
        base_url = TOKEN_CACHE.get("base_url").rstrip("/")
        parsed = urlparse(base_url)
        domain_parts = parsed.netloc.split('.')
        subdomain = domain_parts[0] if domain_parts else "api"
        scheduler_base = f"https://{subdomain}.services.carestack.com/scheduler/api/v1.0"
        
        cal_resp = requests.get(f"{scheduler_base}/production-calender/template", headers=headers, params={"locationId": locationId}, timeout=30)
        prov_resp = requests.get(f"{scheduler_base}/provider-availability/template", headers=headers, params={"locationId": locationId}, timeout=30)
        
        return {
            "calendar": cal_resp.json() if cal_resp.status_code == 200 else str(cal_resp.text),
            "provider": prov_resp.json() if prov_resp.status_code == 200 else str(prov_resp.text)
        }
    except Exception as e:
        return {"error": str(e)}


# --- Legacy endpoints (kept for backwards compatibility) ---

@app.post("/api/fetch-details")
def fetch_details(creds: FetchDetailsRequest):
    try:
        token = get_carestack_token(creds)
        api_base_url = creds.base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {token}"}

        params = [('locationId', lid) for lid in creds.selected_location_ids]
        prov_resp = requests.get(f"{api_base_url}/api/v1.0/providers", headers=headers, params=params, timeout=30)
        prov_resp.raise_for_status()
        raw_providers = prov_resp.json()

        pt_params = [('locationId', lid) for lid in creds.selected_location_ids]
        pt_resp = requests.get(f"{api_base_url}/api/v1.0/production-types", headers=headers, params=pt_params, timeout=30)
        pt_resp.raise_for_status()
        raw_production_types = pt_resp.json()

        op_resp = requests.get(f"{api_base_url}/api/v1.0/operatories", headers=headers, timeout=30)
        op_resp.raise_for_status()
        raw_operatories = op_resp.json()

        providers = []
        for p in raw_providers:
            if not p.get("isActive"):
                continue
            providers.append({
                "id": p.get("id"),
                "name": f"{p.get('firstName', '')} {p.get('lastName', '')}".strip(),
                "specialty": str(p.get("providerType", "General")),
                "specialityId": p.get("specialityId"),
                "concurrency": 1
            })

        production_types = []
        for pt in raw_production_types:
            production_types.append({
                "id": pt.get("id"),
                "name": pt.get("name"),
                "specialty": "General",
                "duration": 30
            })

        operatories = []
        for op in raw_operatories:
            if op.get("locationId") in creds.selected_location_ids:
                operatories.append({
                    "id": op.get("id"),
                    "name": op.get("name"),
                    "location_id": op.get("locationId")
                })

        return {
            "providers": providers,
            "production_types": production_types,
            "operatories": operatories
        }

    except requests.RequestException as e:
        error_msg = str(e)
        if getattr(e, 'response', None) is not None:
            logger.error(f"API Error Response: {e.response.text}")
            error_msg += f" | Response: {e.response.text}"
        logger.error(f"API Request failed: {error_msg}")
        raise HTTPException(status_code=400, detail=f"API Request failed: {error_msg}")
    except Exception as e:
        logger.exception("Internal Error during fetch_details")
        raise HTTPException(status_code=500, detail=f"Internal Error: {str(e)}")


@app.post("/api/save-config-excel")
async def save_config_excel(config: SaveConfigRequest):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:

        # Sheet 1: General Info
        general_data = {
            "Setting": ["Bot Enabled", "Excluded Insurance", "Additional Notes"],
            "Value": [config.botEnabled, config.excludedInsurance, config.notes]
        }
        df_general = pd.DataFrame(general_data)
        df_general.to_excel(writer, sheet_name='General Settings', index=False)

        # Sheet 2: Selected Locations
        selected_loc_ids = [int(loc_id) for loc_id in config.locations]
        selected_locs_data = [l for l in config.full_locations if int(l['id']) in selected_loc_ids]

        if selected_locs_data:
            df_locs = pd.DataFrame(selected_locs_data)
            cols = [c for c in ["id", "name", "address", "phone"] if c in df_locs.columns]
            df_locs = df_locs[cols]
            df_locs.columns = ["Location ID", "Location Name", "Address", "Phone"][:len(cols)]
            df_locs.to_excel(writer, sheet_name='Selected Locations', index=False)
        else:
            pd.DataFrame({"Message": ["No locations selected"]}).to_excel(writer, sheet_name='Selected Locations', index=False)

        # Sheet 3: Selected Providers & Production Types
        provider_rows = []
        selected_prov_ids = [int(pid) for pid in config.providers]

        for p_data in config.full_providers:
            p_id = int(p_data['id'])
            if p_id in selected_prov_ids:
                pt_ids = config.productionTypes.get(str(p_id), [])
                if not pt_ids:
                    # Also try integer key if str fails
                    pt_ids = config.productionTypes.get(p_id, [])

                if not pt_ids:
                    provider_rows.append({
                        "Provider ID": p_id,
                        "Provider Name": p_data.get('name', ''),
                        "Specialty": p_data.get('specialty', p_data.get('providerType', '')),
                        "Concurrency (User Info)": p_data.get('concurrency', 'N/A'),
                        "Concurrent (Availability Template)": p_data.get('concurrentFromTemplate', False),
                        "Production Type ID": "N/A",
                        "Production Type Name": "N/A",
                        "PT Default Duration": "N/A",
                        "PT Calendar Durations": "N/A",
                        "PT Calendar Days": "N/A",
                        "PT Calendar Templates": "N/A",
                        "PT Scheduled Days": "N/A",
                        "PT Scheduled Templates": "N/A",
                        "PT Specialty Count": "N/A"
                    })
                else:
                    for pt_id in pt_ids:
                        pt_data = next((pt for pt in config.full_production_types if int(pt['id']) == int(pt_id)), None)
                        provider_rows.append({
                            "Provider ID": p_id,
                            "Provider Name": p_data.get('name', ''),
                            "Specialty": p_data.get('specialty', p_data.get('providerType', '')),
                            "Concurrency (User Info)": p_data.get('concurrency', 'N/A'),
                            "Concurrent (Availability Template)": p_data.get('concurrentFromTemplate', False),
                            "Production Type ID": pt_id,
                            "Production Type Name": pt_data['name'] if pt_data else "Unknown",
                            "PT Default Duration": pt_data.get('durationMinutes', 0) if pt_data else 0,
                            "PT Calendar Durations": ", ".join(map(str, pt_data.get('calendarDurations', []))) if pt_data else "",
                            "PT Calendar Days": pt_data.get('calendarDays', 'None') if pt_data else "None",
                            "PT Calendar Templates": pt_data.get('calendarTemplates', 'None') if pt_data else "None",
                            "PT Scheduled Days": pt_data.get('scheduledDays', 'None') if pt_data else "None",
                            "PT Scheduled Templates": pt_data.get('scheduledTemplates', 'None') if pt_data else "None",
                            "PT Specialty Count": pt_data.get('specialtyCount', 0) if pt_data else 0
                        })

        if provider_rows:
            df_provs = pd.DataFrame(provider_rows)
            df_provs.to_excel(writer, sheet_name='Providers & PTs', index=False)
        else:
            pd.DataFrame({"Message": ["No providers selected"]}).to_excel(writer, sheet_name='Providers & PTs', index=False)

    output.seek(0)

    resp_headers = {
        'Content-Disposition': 'attachment; filename="voicebot_config.xlsx"'
    }
    return Response(
        content=output.getvalue(),
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers=resp_headers
    )


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        uvicorn.run(app, host="0.0.0.0", port=8000)
    else:
        # Running from source
        uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
