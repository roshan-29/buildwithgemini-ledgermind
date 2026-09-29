# ruff: noqa
# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import datetime
import uuid
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from a2ui.basic_catalog.provider import BasicCatalog
from a2ui.schema.manager import A2uiSchemaManager
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.models import Gemini
from google.adk.tools import ToolContext
from google.adk.tools.preload_memory_tool import PreloadMemoryTool
from google import genai
from google.cloud import firestore, storage
from google.genai import types

from app.a2ui_utils import a2ui_callback

MODEL = "gemini-3.6-flash"
GCP_PROJECT_ID = "qwiklabs-gcp-04-971e8638e31a"
GCS_BUCKET_NAME = "ledgermind-media-qwiklabs-gcp-04-971e8638e31a"
AGENT_ENGINE_ID = "projects/825652234061/locations/us-east1/reasoningEngines/8086580367827402752"

# Initialize Firestore with hardcoded GCP Project ID
db = firestore.Client(project=GCP_PROJECT_ID)
expenses_ref = db.collection("expenses")
budgets_ref = db.collection("budgets")

# Initialize Storage with hardcoded GCP Project ID and Bucket
storage_client = storage.Client(project=GCP_PROJECT_ID)
storage_bucket = storage_client.bucket(GCS_BUCKET_NAME)

# Initialize GenAI Client for multimodal image generation in global location
genai_client = genai.Client(vertexai=True, project=GCP_PROJECT_ID, location="global")


def log_expense(
    amount: float,
    merchant: str,
    category: str,
    date: Optional[str] = None,
    payment_method: str = "Credit Card",
    description: str = "",
) -> Dict[str, Any]:
    """Logs a new expense transaction into Firestore.

    Args:
        amount: The total expense amount (e.g. 45.50).
        merchant: The name of the store, vendor, or service (e.g. Trader Joe's, Netflix).
        category: The category (e.g. Groceries, Dining, Utilities, Entertainment, Transportation).
        date: The date of the expense formatted as YYYY-MM-DD. Defaults to today's date if omitted.
        payment_method: Payment method used (e.g. Credit Card, Apple Pay, Debit Card, Cash, Bank Transfer).
        description: Brief description or details of the purchase.

    Returns:
        A dictionary containing status and the created expense details including ID.
    """
    if not date:
        date = datetime.date.today().isoformat()

    data = {
        "amount": round(float(amount), 2),
        "merchant": merchant.strip(),
        "category": category.strip().title(),
        "date": date,
        "payment_method": payment_method.strip(),
        "description": description.strip(),
        "created_at": firestore.SERVER_TIMESTAMP,
    }
    doc_ref = expenses_ref.document()
    doc_ref.set(data)
    return {
        "status": "success",
        "expense_id": doc_ref.id,
        "expense": {
            "amount": data["amount"],
            "merchant": data["merchant"],
            "category": data["category"],
            "date": data["date"],
            "payment_method": data["payment_method"],
            "description": data["description"],
        },
    }


def list_expenses(
    category: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Retrieves recorded expenses from Firestore, optionally filtered by category.

    Args:
        category: Optional category name to filter by (e.g. Dining, Groceries, Utilities).
        limit: Maximum number of transactions to return (default 20).

    Returns:
        A list of expense dictionaries with id, amount, merchant, category, date, and payment method.
    """
    query = expenses_ref.order_by("date", direction=firestore.Query.DESCENDING).limit(limit)
    if category:
        query = query.where("category", "==", category.strip().title())

    results = []
    for doc in query.stream():
        item = doc.to_dict()
        item["id"] = doc.id
        if "created_at" in item:
            item.pop("created_at", None)
        results.append(item)

    return results


def get_spending_summary() -> Dict[str, Any]:
    """Calculates overall total spending and breakdown by category across all logged expenses.

    Returns:
        A dictionary with total spending, transaction count, and category-by-category subtotals.
    """
    all_expenses = expenses_ref.stream()
    total_spent = 0.0
    category_totals: Dict[str, float] = {}
    count = 0

    for doc in all_expenses:
        item = doc.to_dict()
        amount = float(item.get("amount", 0.0))
        cat = item.get("category", "Other")
        total_spent += amount
        category_totals[cat] = category_totals.get(cat, 0.0) + amount
        count += 1

    return {
        "total_spent": round(total_spent, 2),
        "total_transactions": count,
        "category_breakdown": {k: round(v, 2) for k, v in category_totals.items()},
    }


def manage_category_budget(
    category: str,
    monthly_limit: Optional[float] = None,
) -> Dict[str, Any]:
    """Sets, updates, or checks a monthly budget limit for a specific category against current expenses.

    Args:
        category: The expense category (e.g. Dining, Groceries, Utilities, Entertainment, Transportation).
        monthly_limit: If provided, sets or updates the monthly limit. If omitted or None, only checks the status.

    Returns:
        A dictionary with category, monthly_limit, spent_amount, remaining, and status.
    """
    cat_key = category.strip().title()
    doc_ref = budgets_ref.document(cat_key)

    if monthly_limit is not None and monthly_limit > 0:
        doc_ref.set({
            "category": cat_key,
            "monthly_limit": round(float(monthly_limit), 2),
            "updated_at": firestore.SERVER_TIMESTAMP,
        })
        limit = round(float(monthly_limit), 2)
    else:
        doc = doc_ref.get()
        if doc.exists:
            limit = float(doc.to_dict().get("monthly_limit", 0.0))
        else:
            limit = None

    # Calculate current total spent in this category
    expenses = expenses_ref.where("category", "==", cat_key).stream()
    spent = round(sum(float(e.to_dict().get("amount", 0.0)) for e in expenses), 2)

    if limit is not None:
        remaining = round(limit - spent, 2)
        pct_used = round((spent / limit) * 100, 1) if limit > 0 else 0
        if remaining < 0:
            status = f"OVER_BUDGET by ${abs(remaining):.2f}"
        else:
            status = f"{pct_used}% used (${remaining:.2f} remaining)"
    else:
        remaining = None
        status = "No budget limit set for this category"

    return {
        "category": cat_key,
        "monthly_limit": limit,
        "spent": spent,
        "remaining": remaining,
        "status": status,
    }


def convert_currency(
    amount: float,
    from_currency: str = "USD",
    to_currency: str = "EUR",
) -> Dict[str, Any]:
    """Converts a monetary amount between currencies using real-time rates from ExchangeRate-API.

    Args:
        amount: The monetary amount to convert.
        from_currency: 3-letter currency code to convert from (e.g. USD, EUR, GBP, JPY, CAD).
        to_currency: 3-letter currency code to convert to (e.g. EUR, GBP, JPY, CAD, MXN).

    Returns:
        A dictionary with the original amount, converted amount, exchange rate, and date.
    """
    import urllib.request
    import json

    base = from_currency.strip().upper()
    target = to_currency.strip().upper()
    url = f"https://open.er-api.com/v6/latest/{base}"

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "LedgerMind-Agent/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
        
        rates = data.get("rates", {})
        if target not in rates:
            return {"error": f"Currency code '{target}' not supported or found."}

        rate = rates[target]
        converted = round(float(amount) * rate, 2)
        return {
            "from_currency": base,
            "to_currency": target,
            "original_amount": round(float(amount), 2),
            "converted_amount": converted,
            "exchange_rate": rate,
            "last_updated": data.get("time_last_update_utc", ""),
        }
    except Exception as e:
        return {"error": f"Failed to fetch exchange rates: {str(e)}"}


def geocode_address(address: str) -> Dict[str, Any]:
    """Uses the Google Maps Geocoding API to turn an address into geographic coordinates.

    Args:
        address: The street address, city, or place name (e.g. '1600 Amphitheatre Pkwy, Mountain View, CA' or 'San Francisco, CA').

    Returns:
        A dictionary containing the formatted address, latitude, and longitude.
    """
    import os
    import urllib.parse
    import urllib.request
    import json

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    encoded_addr = urllib.parse.quote(address)
    url = f"https://maps.googleapis.com/maps/api/geocode/json?address={encoded_addr}&key={api_key}"

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))

        if data.get("status") == "OK" and data.get("results"):
            result = data["results"][0]
            loc = result.get("geometry", {}).get("location", {})
            return {
                "name": address,
                "address": result.get("formatted_address", ""),
                "location": {
                    "latitude": loc.get("lat"),
                    "longitude": loc.get("lng"),
                },
            }
        return {"error": f"Geocoding failed with status: {data.get('status')}"}
    except Exception as e:
        return {"error": f"Failed to geocode address: {str(e)}"}


def find_nearby_places(
    latitude: float,
    longitude: float,
    place_type: str = "supermarket",
    radius_meters: float = 1000.0,
    max_results: int = 5,
) -> List[Dict[str, Any]]:
    """Uses the Google Maps Places API (New) to search for nearby places of a given type.

    Args:
        latitude: Latitude of the center location.
        longitude: Longitude of the center location.
        place_type: Place type to search for (e.g. 'supermarket', 'restaurant', 'cafe', 'bank', 'atm', 'gas_station').
        radius_meters: Search radius in meters (default 1000m).
        max_results: Maximum places to return (default 5).

    Returns:
        A list of places, each with name, address, and location coordinates.
    """
    import os
    import urllib.request
    import json
    import google.auth
    import google.auth.transport.requests

    url = "https://places.googleapis.com/v1/places:searchNearby"
    headers = {
        "Content-Type": "application/json",
        "X-Goog-FieldMask": "places.displayName,places.formattedAddress,places.location",
    }

    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    try:
        credentials, project = google.auth.default()
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req)
        headers["Authorization"] = f"Bearer {credentials.token}"
        headers["X-Goog-User-Project"] = GCP_PROJECT_ID
    except Exception:
        if api_key:
            headers["X-Goog-Api-Key"] = api_key

    body = {
        "includedTypes": [place_type.lower().strip()],
        "maxResultCount": min(max_results, 10),
        "locationRestriction": {
            "circle": {
                "center": {
                    "latitude": latitude,
                    "longitude": longitude,
                },
                "radius": float(radius_meters),
            }
        },
    }

    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))

        places = []
        for p in data.get("places", []):
            places.append({
                "name": p.get("displayName", {}).get("text", "Unknown"),
                "address": p.get("formattedAddress", ""),
                "location": {
                    "latitude": p.get("location", {}).get("latitude"),
                    "longitude": p.get("location", {}).get("longitude"),
                },
            })
        return places
    except Exception as e:
        return [{"error": f"Failed to find nearby places: {str(e)}"}]


async def generate_finance_badge(
    title: str,
    tool_context: ToolContext,
    category_or_goal: str = "Savings Milestone",
) -> Dict[str, Any]:
    """Generates a visual badge/icon for a financial achievement or category milestone.

    Uses the gemini-3.1-flash-lite-image model in global region to create an image,
    saves the image as an artifact via tool_context.save_artifact, and uploads it
    to Google Cloud Storage returning its public HTTPS URL.

    Args:
        title: Title of the badge or milestone (e.g. 'Frugal Gourmet', 'Budget Master', 'First $500 Saved').
        category_or_goal: The financial category or savings goal the badge represents.
        tool_context: Injected by ADK runtime to save artifacts to the current session.

    Returns:
        A dictionary with the badge title, public Cloud Storage image URL, and artifact status.
    """
    prompt = (
        f"A modern, vibrant, minimalist 3D vector-style digital achievement badge for personal finance: "
        f"'{title}' related to {category_or_goal}. Clean white background, glossy finish, high quality illustration."
    )

    try:
        response = genai_client.models.generate_content(
            model="gemini-3.1-flash-lite-image",
            contents=prompt,
        )

        image_bytes = None
        mime_type = "image/jpeg"
        if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
            for part in response.candidates[0].content.parts:
                if part.inline_data:
                    image_bytes = part.inline_data.data
                    mime_type = part.inline_data.mime_type or "image/jpeg"
                    break

        if not image_bytes:
            return {"error": "Image model did not return image bytes."}

        # 1. Save with tool_context.save_artifact for Playground Artifacts panel
        filename = f"badge_{uuid.uuid4().hex[:8]}.jpg"
        image_artifact = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
        version = await tool_context.save_artifact(filename=filename, artifact=image_artifact)

        # 2. Upload to public Cloud Storage bucket
        object_name = f"badges/{filename}"
        blob = storage_bucket.blob(object_name)
        blob.upload_from_string(image_bytes, content_type=mime_type)
        public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{object_name}"

        return {
            "title": title,
            "category_or_goal": category_or_goal,
            "artifact_filename": filename,
            "artifact_version": version,
            "public_image_url": public_url,
        }
    except Exception as e:
        return {"error": f"Failed to generate and save badge image: {str(e)}"}


async def generate_finance_video(
    topic: str,
    tool_context: ToolContext,
    visual_style: str = "cinematic 3D animation",
) -> Dict[str, Any]:
    """Generates a short celebratory or summary video for an item in LedgerMind's domain.

    Uses Google's Omni model (gemini-omni-flash-preview) in the global region.
    Saves the video as an artifact via tool_context.save_artifact so it appears in the
    Playground's Artifacts panel, uploads the video bytes directly to the public Cloud Storage
    bucket ('ledgermind-media-qwiklabs-gcp-04-971e8638e31a'), and returns its public HTTPS URL.

    Args:
        topic: The finance topic, milestone, or concept to visualize (e.g. 'savings goal achieved',
               'crypto investment growth', 'debt-free celebration', 'monthly budget mastery').
        tool_context: Injected by ADK runtime to save artifacts to the current session.
        visual_style: Visual aesthetic description, e.g. 'cinematic 3D animation' or 'clean isometric finance'.

    Returns:
        A dictionary with the video topic, public Cloud Storage video URL, and artifact status.
    """
    prompt = (
        f"A short, high-resolution {visual_style} depicting {topic} in personal finance. "
        f"Glossy coins, vibrant emerald green upward charts, clean modern financial aesthetic, smooth movement."
    )

    try:
        # Use Omni model in global region via interactions API
        interaction = genai_client.interactions.create(
            model="gemini-omni-flash-preview",
            input=prompt,
        )

        video_bytes = None
        mime_type = "video/mp4"

        if hasattr(interaction, "output_video") and interaction.output_video:
            if hasattr(interaction.output_video, "data") and interaction.output_video.data:
                video_bytes = base64.b64decode(interaction.output_video.data)
                mime_type = getattr(interaction.output_video, "mime_type", "video/mp4") or "video/mp4"

        if not video_bytes and hasattr(interaction, "outputs") and interaction.outputs:
            for out in interaction.outputs:
                if hasattr(out, "video") and out.video and getattr(out.video, "data", None):
                    video_bytes = base64.b64decode(out.video.data)
                    mime_type = getattr(out.video, "mime_type", "video/mp4") or "video/mp4"
                    break

        if not video_bytes:
            return {"error": "Omni model did not return video bytes."}

        # 1. Save with tool_context.save_artifact so it shows up in Playground's Artifacts panel
        filename = f"video_{uuid.uuid4().hex[:8]}.mp4"
        video_artifact = types.Part.from_bytes(data=video_bytes, mime_type=mime_type)
        version = await tool_context.save_artifact(filename=filename, artifact=video_artifact)

        # 2. Upload same bytes directly to the public Cloud Storage bucket without writing to a local file
        object_name = f"videos/{filename}"
        blob = storage_bucket.blob(object_name)
        blob.upload_from_string(video_bytes, content_type=mime_type)
        public_url = f"https://storage.googleapis.com/{GCS_BUCKET_NAME}/{object_name}"

        return {
            "topic": topic,
            "artifact_filename": filename,
            "artifact_version": version,
            "public_video_url": public_url,
        }
    except Exception as e:
        return {"error": f"Failed to generate and save video with Omni model: {str(e)}"}


SANDBOX_RESOURCE_NAME = (
    "projects/825652234061/locations/us-east1/reasoningEngines/8086580367827402752/"
    "sandboxEnvironments/5902609426459656192"
)


# Memory generation callback for Memory Bank long-term persistence
async def generate_memories_callback(callback_context: CallbackContext):
    await callback_context.add_session_to_memory()
    return None


# Build A2UI system prompt using version 0.8 and Basic Catalog
schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description=(
        "You are LedgerMind, an intelligent personal finance and expense tracking assistant. "
        "You help users manage and inspect their finances effortlessly. "
        "You remember the user's stated financial goals, income, saving preferences, constraints, "
        "and especially all user allergies, dietary restrictions, and food sensitivities "
        "across conversations to provide deeply personalized financial and lifestyle guidance. "
        "Whenever a user mentions any allergy, dietary requirement, or intolerance, acknowledge and remember it. "
        "You have direct access to Firestore tools to log new expenses (`log_expense`), "
        "retrieve transaction histories (`list_expenses`), view category breakdowns (`get_spending_summary`), "
        "manage monthly category budgets (`manage_category_budget`), "
        "convert foreign currency expenses to local rates (`convert_currency`), "
        "find nearby stores or geolocate addresses (`geocode_address`, `find_nearby_places`), "
        "generate financial achievement badges/milestones (`generate_finance_badge`), "
        "and generate celebratory or conceptual 3D finance videos (`generate_finance_video`). "
        "You can also write and execute Python code in an Agent Engine secure sandbox for complex math, "
        "financial projections, compound interest, or data analysis. "
        "Always confirm details when recording new transactions or setting budget goals, and provide clear summaries."
    ),
    workflow_description="Analyze the user request, call any appropriate tools to retrieve or update financial data, and return structured UI when appropriate.",
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > a few Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image (for example the URL an image tool returns after uploading "
        "to a public bucket). Set the Image url to that exact https link, for example "
        "{\"Image\": {\"url\": {\"literalString\": \"https://...\"}}}. Never point an "
        "Image at a bare filename, an artifact name, or a non-http(s) path. If you do "
        "not have a public URL, add a short Text line noting the image instead. "
        "No markdown in text; use the usageHint property ('h1', 'h2', 'body') for "
        "headings and emphasis. "
        "Output ONLY the raw A2UI JSON array — no prose, and never wrap it in "
        "<a2a_datapart_json> tags or 'kind'/'data'/'metadata' objects."
    ),
    include_schema=True,
    include_examples=True,
)


root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    code_executor=AgentEngineSandboxCodeExecutor(
        sandbox_resource_name=SANDBOX_RESOURCE_NAME,
        agent_engine_resource_name=AGENT_ENGINE_ID,
    ),
    instruction=instruction,
    tools=[
        PreloadMemoryTool(),
        log_expense,
        list_expenses,
        get_spending_summary,
        manage_category_budget,
        convert_currency,
        geocode_address,
        find_nearby_places,
        generate_finance_badge,
        generate_finance_video,
    ],
    after_model_callback=a2ui_callback,
    after_agent_callback=generate_memories_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
