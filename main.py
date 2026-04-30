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
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

# Load environment variables from the app directory
load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

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

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

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
    return templates.TemplateResponse("index.html", {
        "request": request,
        "v": int(time.time()),
        "carestack_api_url": os.getenv("CARESTACK_API_URL", "")
    })


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
        with ThreadPoolExecutor(max_workers=6) as executor:
            future_providers = executor.submit(_fetch_providers)
            future_pts = executor.submit(_fetch_production_types)
            future_ops = executor.submit(_fetch_operatories)
            future_sched = executor.submit(_fetch_scheduler_pts)
            future_users = executor.submit(_fetch_users)
            future_op_prov = executor.submit(_fetch_operatory_providers)

            raw_providers = future_providers.result()
            raw_pts = future_pts.result()
            raw_ops = future_ops.result()
            raw_sched_pts = future_sched.result()
            raw_users = future_users.result()
            raw_op_prov = future_op_prov.result()


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
            "slot_duration_minutes": SLOT_DURATION_MINUTES,
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
                pt_ids = config.productionTypes.get(p_id, [])
                if not pt_ids:
                    provider_rows.append({
                        "Provider ID": p_id,
                        "Provider Name": p_data.get('name', ''),
                        "Specialty": p_data.get('specialty', p_data.get('providerType', '')),
                        "Concurrency": p_data.get('concurrency', 'N/A'),
                        "Production Type ID": "N/A",
                        "Production Type Name": "N/A"
                    })
                else:
                    for pt_id in pt_ids:
                        pt_data = next((pt for pt in config.full_production_types if int(pt['id']) == int(pt_id)), None)
                        provider_rows.append({
                            "Provider ID": p_id,
                            "Provider Name": p_data.get('name', ''),
                            "Specialty": p_data.get('specialty', p_data.get('providerType', '')),
                            "Concurrency": p_data.get('concurrency', 'N/A'),
                            "Production Type ID": pt_id,
                            "Production Type Name": pt_data['name'] if pt_data else "Unknown"
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
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
