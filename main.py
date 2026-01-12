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

# Load environment variables
load_dotenv()

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
    "auth_url": None
}

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# Mock Data
LOCATIONS = [
    {"id": 1, "name": "Downtown Clinic", "address": "123 Main St", "phone": "555-0100"},
    {"id": 2, "name": "Westside Branch", "address": "456 West Ave", "phone": "555-0101"},
]

PROVIDERS = [
    {"id": 101, "name": "Dr. Smith", "specialty": "General", "concurrency": 2},
    {"id": 102, "name": "Dr. Jones", "specialty": "Orthodontics", "concurrency": 1},
    {"id": 103, "name": "Dr. Doe", "specialty": "General", "concurrency": 1},
]

PRODUCTION_TYPES = [
    {"id": 201, "name": "Exam", "specialty": "General", "duration": 30},
    {"id": 202, "name": "Cleaning", "specialty": "General", "duration": 45},
    {"id": 203, "name": "Braces Checkup", "specialty": "Orthodontics", "duration": 20},
]

OPERATORIES = [
    {"id": 301, "name": "Op 1", "location_id": 1},
    {"id": 302, "name": "Op 2", "location_id": 1},
    {"id": 303, "name": "Op A", "location_id": 2},
]

# Mapping for validation (Provider -> Operatory)
PROVIDER_OPERATORY_MAP = {
    101: [301, 302],  # Dr. Smith in Op 1 and Op 2
    102: [303],       # Dr. Jones in Op A
    103: [],          # Dr. Doe has no operatories (Error case)
}

# Mapping for validation (Operatory -> Production Type Blocks)
OPERATORY_BLOCK_MAP = {
    301: [201, 202],
    302: [201],
    303: [203],
}

class ValidationRequest(BaseModel):
    selected_location_ids: List[int]
    selected_provider_ids: List[int]
    selected_production_type_ids: Dict[int, List[int]]  # provider_id -> list of production_type_ids
    locations: Optional[List[Dict[str, Any]]] = []
    providers: Optional[List[Dict[str, Any]]] = []
    production_types: Optional[List[Dict[str, Any]]] = []
    operatories: Optional[List[Dict[str, Any]]] = []

class BaseFetchRequest(BaseModel):
    auth_url: str
    base_url: str
    username: str
    password: Optional[str] = ""
    client_id: str
    client_secret: str

class FetchDetailsRequest(BaseFetchRequest):
    selected_location_ids: List[int]

class FetchUserDetailRequest(BaseFetchRequest):
    user_detail_id: str | int

class SaveConfigRequest(BaseModel):
    locations: List[Any]
    providers: List[Any] # Only IDs really needed but let's take objects for simplicity if provided
    productionTypes: Dict[int, List[int]]
    excludedInsurance: str
    notes: str
    botEnabled: bool
    # We might need full location objects and provider names to populate the excel nicely without re-fetching mock/state
    # So let's expect the frontend to send enough info.
    full_locations: List[Dict[str, Any]]
    full_providers: List[Dict[str, Any]]
    full_production_types: List[Dict[str, Any]]

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "v": int(time.time()),
        "carestack_api_url": os.getenv("CARESTACK_API_URL", ""),
        "carestack_auth_url": os.getenv("CARESTACK_AUTH_URL", ""),
        "carestack_username": os.getenv("CARESTACK_USERNAME", ""),
        "carestack_client_id": os.getenv("CARESTACK_CLIENT_ID", ""),
        "carestack_client_secret": os.getenv("CARESTACK_CLIENT_SECRET", "")
    })

@app.get("/api/locations")
async def get_locations():
    return LOCATIONS

@app.get("/api/providers")
async def get_providers():
    return PROVIDERS

@app.get("/api/production-types")
async def get_production_types():
    return PRODUCTION_TYPES

def get_carestack_token(creds: BaseFetchRequest):
    auth_base_url = creds.auth_url.rstrip("/")
    auth_url = f"{auth_base_url}/connect/token"
    token = None
    
    global TOKEN_CACHE
    now = time.time()

    # Check if we have a valid cached token for the same auth URL
    if (TOKEN_CACHE["access_token"] and 
        now < TOKEN_CACHE["expires_at"] and 
        TOKEN_CACHE.get("auth_url") == auth_url):
        token = TOKEN_CACHE["access_token"]

    if not token:
        payload = {
            "grant_type": "password",
            "client_id": creds.client_id,
            "client_secret": creds.client_secret,
            "username": creds.username,
            "password": creds.password
        }
        
        auth_resp = requests.post(auth_url, data=payload, timeout=30)
        
        if auth_resp.status_code == 200:
            token = auth_resp.json().get("access_token")
            TOKEN_CACHE["access_token"] = token
            TOKEN_CACHE["expires_at"] = now + (2.5 * 3600)
            TOKEN_CACHE["auth_url"] = auth_url
        else:
             logger.error(f"Authentication failed: {auth_resp.status_code} - {auth_resp.text}")
             raise HTTPException(status_code=400, detail=f"Authentication failed: {auth_resp.text}")

    if not token:
         logger.error("Could not retrieve access token")
         raise HTTPException(status_code=400, detail="Could not retrieve access token")
         
    return token

@app.post("/api/fetch-locations")
def fetch_locations(creds: BaseFetchRequest):
    try:
        token = get_carestack_token(creds)
        api_base_url = creds.base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {token}"}

        # Fetch Locations
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

@app.post("/api/fetch-details")
def fetch_details(creds: FetchDetailsRequest):
    try:
        token = get_carestack_token(creds)
        api_base_url = creds.base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {token}"}

        # Fetch Providers
        params = [('locationId', lid) for lid in creds.selected_location_ids]
        prov_resp = requests.get(f"{api_base_url}/api/v1.0/providers", headers=headers, params=params, timeout=30)
        prov_resp.raise_for_status()
        raw_providers = prov_resp.json()
        
        # Fetch Production Types
        pt_params = [('locationId', lid) for lid in creds.selected_location_ids]
        pt_resp = requests.get(f"{api_base_url}/api/v1.0/production-types", headers=headers, params=pt_params, timeout=30)
        pt_resp.raise_for_status()
        raw_production_types = pt_resp.json()

        # Fetch Operatories
        op_resp = requests.get(f"{api_base_url}/api/v1.0/operatories", headers=headers, timeout=30)
        op_resp.raise_for_status()
        raw_operatories = op_resp.json()

        # Transform Data
        providers = []
        for p in raw_providers:
            if not p.get("isActive"):
                continue
            providers.append({
                "id": p.get("id"),
                "name": f"{p.get('firstName', '')} {p.get('lastName', '')}".strip(),
                "specialty": str(p.get("providerType", "General")),
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
            # Filter operatories by selected locations
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

@app.post("/api/fetch-users")
def fetch_users(creds: BaseFetchRequest):
    try:
        token = get_carestack_token(creds)
        api_base_url = creds.base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {token}"}

        # URL provided by user: https://base_url/setup/user/grid-get-users-all
        url = f"{api_base_url}/setup/user/grid-get-users-all"
        
        # Grid endpoints usually accept a payload
        payload = {
            "PageIndex": 1,
            "PageSize": 1000,
            "OrderBy": "UserDetailID desc",
            "FilterQuery": {"IsActive": True}
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        
        if resp.status_code == 404:
             # Fallback if the path is slightly different or if it's a GET
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
                 
        # Filter users to only those with a ProviderID
        filtered_users = []
        for u in users_list:
            pid = u.get("ProviderID")
            # Check if not None, not "null" (string)
            if pid is not None and str(pid).lower() != "null":
                # For this specific task, we need MaxConcurrentAppointments.
                # However, the grid endpoint might NOT return it.
                # We might need to fetch details for EACH user if it's not in the grid data.
                # Let's check if the sample output implies it comes from the detail endpoint.
                # The user query implies showing it as a column.
                
                # OPTIMIZATION: If the grid data doesn't have it, we have to make N calls.
                # But let's assume for now we might need to fetch it or it's not there.
                # The prompt implies "display only the MaxConcurrentAppointments... remove the button".
                # This suggests we should fetch this info automatically.
                
                # Fetch detailed info for this user to get MaxConcurrentAppointments
                # WARNING: This will be slow for many users (N+1 problem).
                # But based on the request, we must show it.
                
                try:
                    detail_url = f"{api_base_url}/setup/user/get/{u.get('UserDetailID')}"
                    detail_resp = requests.get(detail_url, headers=headers, timeout=10)
                    if detail_resp.status_code == 200:
                        detail_data = detail_resp.json()
                        provider_info = detail_data.get("Provider", {})
                        u["MaxConcurrentAppointments"] = provider_info.get("MaxConcurrentAppointments", "N/A")
                    else:
                         u["MaxConcurrentAppointments"] = "Error"
                except:
                    u["MaxConcurrentAppointments"] = "Error"

                filtered_users.append(u)
        
        return filtered_users

    except requests.RequestException as e:
        error_msg = str(e)
        if getattr(e, 'response', None) is not None:
             logger.error(f"API Error Response: {e.response.text}")
             error_msg += f" | Response: {e.response.text}"
        logger.error(f"API Request failed: {error_msg}")
        raise HTTPException(status_code=400, detail=f"API Request failed: {error_msg}")
    except Exception as e:
        logger.exception("Internal Error during fetch_users")
        raise HTTPException(status_code=500, detail=f"Internal Error: {str(e)}")

@app.post("/api/fetch-user-detail")
def fetch_user_detail(creds: FetchUserDetailRequest):
    try:
        token = get_carestack_token(creds)
        api_base_url = creds.base_url.rstrip("/")
        headers = {"Authorization": f"Bearer {token}"}

        # URL: https://base_url/setup/user/get/{userdetail_id}
        url = f"{api_base_url}/setup/user/get/{creds.user_detail_id}"
        
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        
        data = resp.json()
        logger.info(f"fetched user details for id {creds.user_detail_id}: {data}")
        return data

    except requests.RequestException as e:
        error_msg = str(e)
        if getattr(e, 'response', None) is not None:
             logger.error(f"API Error Response: {e.response.text}")
             error_msg += f" | Response: {e.response.text}"
        logger.error(f"API Request failed: {error_msg}")
        raise HTTPException(status_code=400, detail=f"API Request failed: {error_msg}")
    except Exception as e:
        logger.exception("Internal Error during fetch_user_detail")
        raise HTTPException(status_code=500, detail=f"Internal Error: {str(e)}")

@app.post("/api/fetch-scheduler-production-types")
def fetch_scheduler_production_types(creds: BaseFetchRequest):
    try:
        token = get_carestack_token(creds)
        
        # Construct the URL: https://{base_url}.services.carestack.com/scheduler/api/v1.0/production-types
        parsed = urlparse(creds.base_url)
        domain_parts = parsed.netloc.split('.')
        # Assuming the first part is the tenant/base_url part (e.g. 'api' or 'tenant')
        subdomain = domain_parts[0] if domain_parts else "api"
        
        # Adjust if the input was just a domain without scheme (though requests usually requires scheme)
        if not parsed.scheme and not parsed.netloc:
             # fallback if parsing failed or format is unexpected
             subdomain = "api"

        scheduler_url = f"https://{subdomain}.services.carestack.com/scheduler/api/v1.0/production-types"
        headers = {"Authorization": f"Bearer {token}"}
        
        logger.info(f"Fetching scheduler production types from: {scheduler_url}")
        
        resp = requests.get(scheduler_url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        
        results = []
        # Data is expected to be a list of dicts
        if isinstance(data, list):
            for item in data:
                # Extract providerSpeciality
                specialities = set()
                allocations = item.get("providerAllocation", [])
                if isinstance(allocations, list):
                    for alloc in allocations:
                        spec = alloc.get("providerSpeciality")
                        if spec is not None:
                            specialities.add(str(spec))
                
                # Join if multiple, or just take one. Prompt implies singular output column but multiple could exist.
                # Let's join them with comma
                spec_str = ", ".join(sorted(list(specialities))) if specialities else "N/A"

                results.append({
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "providerSpeciality": spec_str
                })
        
        return results

    except requests.RequestException as e:
        error_msg = str(e)
        if getattr(e, 'response', None) is not None:
             logger.error(f"API Error Response: {e.response.text}")
             error_msg += f" | Response: {e.response.text}"
        logger.error(f"API Request failed: {error_msg}")
        raise HTTPException(status_code=400, detail=f"API Request failed: {error_msg}")
    except Exception as e:
        logger.exception("Internal Error during fetch_scheduler_production_types")
        raise HTTPException(status_code=500, detail=f"Internal Error: {str(e)}")

@app.post("/api/validate")
async def validate_configuration(config: ValidationRequest):
    errors = []
    warnings = []
    
    # Determine data source
    if config.providers:
        # Use fetched data
        providers_src = config.providers
        production_types_src = config.production_types
        operatories_src = config.operatories
        # Mappings not available in fetched data
        provider_operatory_map = {} 
        operatory_block_map = {}
        using_fetched = True
    else:
        # Use mock data
        providers_src = PROVIDERS
        production_types_src = PRODUCTION_TYPES
        operatories_src = OPERATORIES
        provider_operatory_map = PROVIDER_OPERATORY_MAP
        operatory_block_map = OPERATORY_BLOCK_MAP
        using_fetched = False

    # 1. Critical: Provider and Production Type specialties should match
    for provider_id in config.selected_provider_ids:
        # Comparison using str to be safe against int/str mismatch
        provider = next((p for p in providers_src if str(p.get("id")) == str(provider_id)), None)
        if not provider:
            continue
            
        selected_pt_ids = config.selected_production_type_ids.get(provider_id, [])
        for pt_id in selected_pt_ids:
            pt = next((pt for pt in production_types_src if str(pt.get("id")) == str(pt_id)), None)
            if pt and str(pt.get("specialty")) != str(provider.get("specialty")):
                errors.append(f"CRITICAL: Provider {provider.get('name')} ({provider.get('specialty')}) has mismatching Production Type {pt.get('name')} ({pt.get('specialty')}).")

    # 2. Critical: Provider should be mapped to at least one (or more) operator in at least one (or more) given locations.
    for provider_id in config.selected_provider_ids:
        provider = next((p for p in providers_src if str(p.get("id")) == str(provider_id)), None)
        if not provider: continue
        
        if using_fetched:
            # We don't have explicit mapping, so we check if ANY operatory exists in the selected locations.
            valid_op_found = False
            for op in operatories_src:
                if op.get("location_id") in config.selected_location_ids:
                    valid_op_found = True
                    break
            
            if not valid_op_found:
                 errors.append(f"CRITICAL: No operatories found in selected locations. Provider {provider.get('name')} cannot be mapped.")
        else:
            mapped_ops = provider_operatory_map.get(provider_id, [])
            valid_op_found = False
            for op_id in mapped_ops:
                op = next((o for o in operatories_src if o["id"] == op_id), None)
                if op and op["location_id"] in config.selected_location_ids:
                    valid_op_found = True
                    break
            
            if not valid_op_found:
                errors.append(f"CRITICAL: Provider {provider['name']} is not mapped to any operatory in the selected locations.")

    # 3. Critical: Operator mapped to a provider should have at least one or more compatible production type blocks in the scheduler.
    if not using_fetched:
        # Only run this detailed check if we have the map
        for provider_id in config.selected_provider_ids:
            provider = next((p for p in providers_src if str(p.get("id")) == str(provider_id)), None)
            mapped_ops = provider_operatory_map.get(provider_id, [])
            selected_pt_ids = config.selected_production_type_ids.get(provider_id, [])
            
            if not selected_pt_ids:
                 continue 
                 
            for op_id in mapped_ops:
                 op = next((o for o in operatories_src if o["id"] == op_id), None)
                 if op and op["location_id"] in config.selected_location_ids:
                     supported_blocks = operatory_block_map.get(op_id, [])
                     if not any(pt_id in supported_blocks for pt_id in selected_pt_ids):
                         errors.append(f"CRITICAL: Operatory {op['name']} for Provider {provider['name']} does not have compatible production type blocks for selected types.")
    # Note: If using_fetched, we skip this check as we don't have block info.

    # 4. Warnings: Concurrency check
    for provider_id in config.selected_provider_ids:
        provider = next((p for p in providers_src if str(p.get("id")) == str(provider_id)), None)
        if not provider: continue

        if using_fetched:
             # Check how many operatories in selected locations (assuming potentially all are available)
             active_ops_count = len([op for op in operatories_src if op.get("location_id") in config.selected_location_ids])
             
             # Concurrency for fetched data is hardcoded to 1 (in fetch_carestack_data) if not available
             prov_concurrency = provider.get("concurrency", 1)
             if active_ops_count > prov_concurrency:
                 warnings.append(f"WARNING: Provider {provider.get('name')} has concurrency {prov_concurrency} but {active_ops_count} operatories are available in selected locations (Mapping info unavailable).")
        else:
            mapped_ops = provider_operatory_map.get(provider_id, [])
            active_ops = [op_id for op_id in mapped_ops 
                          if next((o for o in operatories_src if o["id"] == op_id), {}).get("location_id") in config.selected_location_ids]
            
            if len(active_ops) > provider["concurrency"]:
                warnings.append(f"WARNING: Provider {provider['name']} is mapped to {len(active_ops)} operatories but has concurrency of {provider['concurrency']}.")

    return {"errors": errors, "warnings": warnings}

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
        # Filter full locations by selected ids
        selected_loc_ids = [int(loc_id) for loc_id in config.locations]
        selected_locs_data = [l for l in config.full_locations if int(l['id']) in selected_loc_ids]
        
        if selected_locs_data:
            df_locs = pd.DataFrame(selected_locs_data)
            # Reorder/Rename columns if needed
            cols = ["id", "name", "address", "phone"]
            # Ensure cols exist
            cols = [c for c in cols if c in df_locs.columns]
            df_locs = df_locs[cols]
            df_locs.columns = ["Location ID", "Location Name", "Address", "Phone"]
            df_locs.to_excel(writer, sheet_name='Selected Locations', index=False)
        else:
            pd.DataFrame({"Message": ["No locations selected"]}).to_excel(writer, sheet_name='Selected Locations', index=False)
            
        # Sheet 3: Selected Providers & Production Types
        # Create a flattened list: Provider -> Production Type
        provider_rows = []
        selected_prov_ids = [int(pid) for pid in config.providers]
        
        for p_data in config.full_providers:
            p_id = int(p_data['id'])
            if p_id in selected_prov_ids:
                # Get PTs
                pt_ids = config.productionTypes.get(p_id, [])
                if not pt_ids:
                    # Provider with no PTs selected
                    provider_rows.append({
                        "Provider ID": p_id,
                        "Provider Name": p_data['name'],
                        "Specialty": p_data['specialty'],
                        "Production Type ID": "N/A",
                        "Production Type Name": "N/A"
                    })
                else:
                    for pt_id in pt_ids:
                        pt_data = next((pt for pt in config.full_production_types if int(pt['id']) == int(pt_id)), None)
                        provider_rows.append({
                            "Provider ID": p_id,
                            "Provider Name": p_data['name'],
                            "Specialty": p_data['specialty'],
                            "Production Type ID": pt_id,
                            "Production Type Name": pt_data['name'] if pt_data else "Unknown"
                        })
                        
        if provider_rows:
            df_provs = pd.DataFrame(provider_rows)
            df_provs.to_excel(writer, sheet_name='Providers & PTs', index=False)
        else:
             pd.DataFrame({"Message": ["No providers selected"]}).to_excel(writer, sheet_name='Providers & PTs', index=False)

    output.seek(0)
    
    headers = {
        'Content-Disposition': 'attachment; filename="voicebot_config.xlsx"'
    }
    return Response(content=output.getvalue(), media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers=headers)

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
