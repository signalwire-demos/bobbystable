"""
═══════════════════════════════════════════════════════════════════════════════
Bobby's Table - Restaurant Reservation System
═══════════════════════════════════════════════════════════════════════════════

A SignalWire AI agent for making restaurant reservations via telephone,
with a web dashboard to view current reservations.

Features:
- Multi-context conversation flow for guided reservation process
- In-memory reservation storage with availability tracking
- Time slot management (5 parties max per hour slot)
- Web API for viewing reservations grouped by date
- Real-time updates to frontend via user events

Usage:
    python app.py                    # Run locally
    gunicorn app:app ...            # Run in production (see Procfile)

Environment Variables (see .env.example):
    SIGNALWIRE_SPACE_NAME           # Required: Your SignalWire space
    SIGNALWIRE_PROJECT_ID           # Required: Your project ID
    SIGNALWIRE_TOKEN                # Required: Your API token
    SWML_PROXY_URL_BASE or APP_URL  # Auto-detected on Dokku/Heroku, set for local

═══════════════════════════════════════════════════════════════════════════════
"""

import os
import time
import logging
import requests
import random
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# ─────────────────────────────────────────────────────────────────────────────
# SignalWire Agents SDK imports
# ─────────────────────────────────────────────────────────────────────────────
from signalwire_agents import AgentBase, AgentServer, SwaigFunctionResult

# Load environment variables from .env file (for local development)
load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# Logging Configuration
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Global State
# ─────────────────────────────────────────────────────────────────────────────
# This dict stores the SWML handler info after registration on startup.
# It's used by the /get_token endpoint to provide the call address to clients.
swml_handler_info = {
    "id": None,           # Handler resource ID
    "address_id": None,   # Address resource ID (used to scope tokens)
    "address": None       # The SIP address clients dial to reach the agent
}

# ─────────────────────────────────────────────────────────────────────────────
# Reservation Data Structures (In-Memory)
# ─────────────────────────────────────────────────────────────────────────────
# Stores all reservations keyed by reservation ID
RESERVATIONS = {}

# Tracks availability per date and time slot
AVAILABILITY = {}

# Configuration
TIME_SLOTS = ["17:00", "18:00", "19:00", "20:00", "21:00"]  # 5pm-9pm
MAX_PER_SLOT = 5  # Maximum reservations per time slot
MAX_PARTY_SIZE = 20


def generate_confirmation_number():
    """Generate a unique 6-digit confirmation number."""
    return str(random.randint(100000, 999999))


def say_digits(number_str: str) -> str:
    """Convert a number string to spoken words for TTS.

    Example: "123456" -> "one two three four five six"
    """
    digit_words = {
        '0': 'zero', '1': 'one', '2': 'two', '3': 'three', '4': 'four',
        '5': 'five', '6': 'six', '7': 'seven', '8': 'eight', '9': 'nine'
    }
    return ' '.join(digit_words.get(d, d) for d in number_str)


def get_slot_availability(date: str, time_slot: str) -> dict:
    """Check availability for a specific date and time slot."""
    if date not in AVAILABILITY:
        AVAILABILITY[date] = {
            slot: {"max": MAX_PER_SLOT, "booked": 0, "reservation_ids": []}
            for slot in TIME_SLOTS
        }

    slot = AVAILABILITY[date].get(time_slot)
    if not slot:
        return {"available": False, "remaining": 0, "reason": "Invalid time slot"}

    remaining = slot["max"] - slot["booked"]
    return {
        "available": remaining > 0,
        "remaining": remaining,
        "reason": None if remaining > 0 else "Time slot is fully booked"
    }


def book_slot(date: str, time_slot: str, reservation_id: str) -> bool:
    """Book a time slot for a reservation."""
    avail = get_slot_availability(date, time_slot)
    if not avail["available"]:
        return False

    AVAILABILITY[date][time_slot]["booked"] += 1
    AVAILABILITY[date][time_slot]["reservation_ids"].append(reservation_id)
    return True


def release_slot(date: str, time_slot: str, reservation_id: str):
    """Release a booked time slot."""
    if date in AVAILABILITY and time_slot in AVAILABILITY[date]:
        slot = AVAILABILITY[date][time_slot]
        if reservation_id in slot["reservation_ids"]:
            slot["reservation_ids"].remove(reservation_id)
            slot["booked"] = max(0, slot["booked"] - 1)

# Server configuration
HOST = "0.0.0.0"
PORT = int(os.environ.get('PORT', 5000))


# ═══════════════════════════════════════════════════════════════════════════════
# SWML Handler Registration Functions
# ═══════════════════════════════════════════════════════════════════════════════
# These functions handle automatic registration of your agent with SignalWire
# so that incoming calls are routed to your SWML endpoint.
#
# URL Detection:
# - On Dokku/Heroku: APP_URL is set automatically by the platform
# - For local dev: Set SWML_PROXY_URL_BASE to your ngrok/tunnel URL
# - The SDK's get_full_url() also auto-detects from X-Forwarded headers at runtime

def get_signalwire_host():
    """
    Get the full SignalWire API host from the space name.

    The space name can be provided as either:
    - Just the space: "myspace" -> "myspace.signalwire.com"
    - Full domain: "myspace.signalwire.com" -> used as-is
    """
    space = os.getenv("SIGNALWIRE_SPACE_NAME", "")
    if not space:
        return None
    if "." in space:
        return space
    return f"{space}.signalwire.com"


def find_sip_address(addresses, agent_name):
    """
    Find the SIP address matching /public/{agent_name} from a list of addresses.

    When phone numbers are attached to a handler, multiple addresses exist.
    We want the SIP address (e.g., /public/bobbystable) not the phone number address.
    """
    expected_address = f"/public/{agent_name}"

    # First, try to find exact match for /public/{agent_name}
    for addr in addresses:
        audio_channel = addr.get("channels", {}).get("audio", "")
        if audio_channel == expected_address:
            return addr

    # Fallback: find any address that looks like a SIP address (not a phone number)
    for addr in addresses:
        audio_channel = addr.get("channels", {}).get("audio", "")
        # SIP addresses start with /public/ and don't contain phone number patterns
        if audio_channel.startswith("/public/") and not any(c.isdigit() for c in audio_channel.split("/")[-1][:3]):
            return addr

    # Last resort: return first address
    return addresses[0] if addresses else None


def find_existing_handler(sw_host, auth, agent_name):
    """
    Find an existing SWML handler by name.

    This prevents creating duplicate handlers on each deployment.
    We search by agent name rather than URL because the URL may change
    (e.g., different basic auth credentials).

    Args:
        sw_host: SignalWire API host (e.g., "myspace.signalwire.com")
        auth: Tuple of (project_id, token) for API authentication
        agent_name: The name to search for

    Returns:
        Dict with handler info if found, None otherwise
    """
    try:
        # List all external SWML handlers in the project
        resp = requests.get(
            f"https://{sw_host}/api/fabric/resources/external_swml_handlers",
            auth=auth,
            headers={"Accept": "application/json"}
        )
        if resp.status_code != 200:
            logger.warning(f"Failed to list handlers: {resp.status_code}")
            return None

        handlers = resp.json().get("data", [])

        for handler in handlers:
            # The name is nested in the swml_webhook object
            swml_webhook = handler.get("swml_webhook", {})
            handler_name = swml_webhook.get("name") or handler.get("display_name")

            # Check if this handler matches our agent name
            if handler_name == agent_name:
                handler_id = handler.get("id")
                handler_url = swml_webhook.get("primary_request_url", "")

                # Get the address for this handler (needed for token scoping)
                addr_resp = requests.get(
                    f"https://{sw_host}/api/fabric/resources/external_swml_handlers/{handler_id}/addresses",
                    auth=auth,
                    headers={"Accept": "application/json"}
                )
                if addr_resp.status_code == 200:
                    addresses = addr_resp.json().get("data", [])
                    sip_addr = find_sip_address(addresses, agent_name)
                    if sip_addr:
                        return {
                            "id": handler_id,
                            "name": handler_name,
                            "url": handler_url,
                            "address_id": sip_addr["id"],
                            "address": sip_addr["channels"]["audio"]
                        }
    except Exception as e:
        logger.error(f"Error finding existing handler: {e}")
    return None


def setup_swml_handler():
    """
    Set up SWML handler on startup.

    This function:
    1. Checks if a handler with our agent name already exists
    2. If yes: Updates the URL (in case credentials changed)
    3. If no: Creates a new handler
    4. Stores the handler info globally for use by /get_token

    The SWML URL includes basic auth credentials embedded in it so that
    SignalWire can authenticate when calling back to our endpoint.

    URL Priority:
    1. SWML_PROXY_URL_BASE (if set explicitly)
    2. APP_URL (auto-set by Dokku/Heroku)
    """
    # Get configuration from environment
    sw_host = get_signalwire_host()
    project = os.getenv("SIGNALWIRE_PROJECT_ID", "")
    token = os.getenv("SIGNALWIRE_TOKEN", "")
    agent_name = os.getenv("AGENT_NAME", "example")

    # URL priority: SWML_PROXY_URL_BASE > APP_URL (auto-set by Dokku/Heroku)
    proxy_url = os.getenv("SWML_PROXY_URL_BASE", os.getenv("APP_URL", ""))
    auth_user = os.getenv("SWML_BASIC_AUTH_USER", "signalwire")
    auth_pass = os.getenv("SWML_BASIC_AUTH_PASSWORD", "")

    # Validate required configuration
    if not all([sw_host, project, token]):
        logger.warning("SignalWire credentials not configured - skipping SWML handler setup")
        return

    if not proxy_url:
        logger.warning("SWML_PROXY_URL_BASE/APP_URL not set - skipping SWML handler setup")
        return

    # Build SWML URL with basic auth credentials embedded
    # Format: https://user:pass@example.com/example
    if auth_user and auth_pass and "://" in proxy_url:
        scheme, rest = proxy_url.split("://", 1)
        swml_url = f"{scheme}://{auth_user}:{auth_pass}@{rest}/{agent_name}"
    else:
        swml_url = f"{proxy_url}/{agent_name}"

    auth = (project, token)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}

    # Look for an existing handler by name
    existing = find_existing_handler(sw_host, auth, agent_name)

    if existing:
        # Handler exists - update the URL (credentials may have changed)
        swml_handler_info["id"] = existing["id"]
        swml_handler_info["address_id"] = existing["address_id"]
        swml_handler_info["address"] = existing["address"]

        try:
            update_resp = requests.put(
                f"https://{sw_host}/api/fabric/resources/external_swml_handlers/{existing['id']}",
                json={
                    "primary_request_url": swml_url,
                    "primary_request_method": "POST"
                },
                auth=auth,
                headers=headers
            )
            update_resp.raise_for_status()
            logger.info(f"Updated SWML handler: {existing['name']}")
        except Exception as e:
            logger.error(f"Failed to update handler URL: {e}")

        logger.info(f"Call address: {existing['address']}")
    else:
        # Create a new external SWML handler
        try:
            handler_resp = requests.post(
                f"https://{sw_host}/api/fabric/resources/external_swml_handlers",
                json={
                    "name": agent_name,
                    "used_for": "calling",
                    "primary_request_url": swml_url,
                    "primary_request_method": "POST"
                },
                auth=auth,
                headers=headers
            )
            handler_resp.raise_for_status()
            handler_id = handler_resp.json().get("id")
            swml_handler_info["id"] = handler_id

            # Get the address for this handler
            addr_resp = requests.get(
                f"https://{sw_host}/api/fabric/resources/external_swml_handlers/{handler_id}/addresses",
                auth=auth,
                headers={"Accept": "application/json"}
            )
            addr_resp.raise_for_status()
            addresses = addr_resp.json().get("data", [])
            sip_addr = find_sip_address(addresses, agent_name)
            if sip_addr:
                swml_handler_info["address_id"] = sip_addr["id"]
                swml_handler_info["address"] = sip_addr["channels"]["audio"]

            logger.info(f"Created SWML handler '{agent_name}' with address: {swml_handler_info.get('address')}")
        except Exception as e:
            logger.error(f"Failed to create SWML handler: {e}")
            # Retry finding existing handler (another worker may have just created it)
            time.sleep(0.5)
            existing = find_existing_handler(sw_host, auth, agent_name)
            if existing:
                swml_handler_info["id"] = existing["id"]
                swml_handler_info["address_id"] = existing["address_id"]
                swml_handler_info["address"] = existing["address"]
                logger.info(f"Found existing SWML handler after retry: {existing['name']}")
                logger.info(f"Call address: {existing['address']}")


# ═══════════════════════════════════════════════════════════════════════════════
# Agent Definition
# ═══════════════════════════════════════════════════════════════════════════════
# The agent class defines the AI personality, conversation flow, and tools (SWAIG
# functions) that the agent can use.

class ReservationAgent(AgentBase):
    """
    Bobby's Table - Restaurant Reservation Agent.

    This agent uses a multi-context workflow to guide callers through
    making, modifying, or canceling reservations.
    """

    def __init__(self):
        """Initialize the agent with name and route."""
        super().__init__(
            name="Bobby's Table",
            route="/bobbystable"
        )

        self._setup_prompts()
        self._setup_contexts()
        self._setup_functions()

    def _setup_prompts(self):
        """Configure the agent's personality."""
        self.prompt_add_section(
            "Role",
            "You are the host at Bobby's Table, an upscale restaurant. "
            "You help guests make, modify, or cancel reservations. "
            "Be warm, professional, and welcoming."
        )

        self.prompt_add_section(
            "Reservation Flow",
            "When collecting a new reservation, gather info in this order: "
            "1) Name, 2) Party size, 3) Date (convert 'tomorrow' etc to YYYY-MM-DD), "
            "4) Time slot, 5) Phone number, 6) Special requests. "
            "Call each function as you collect each piece of info. "
            "After special requests, the system will show confirmation."
        )

        self.prompt_add_section(
            "Guidelines",
            bullets=[
                "Always confirm reservation details before finalizing",
                "Suggest alternative times if requested slot is full",
                "Convert natural language dates to YYYY-MM-DD format"
            ]
        )

        self.prompt_add_section(
            "Time Slots",
            f"Available time slots are: {', '.join(TIME_SLOTS)} (5 PM to 9 PM). "
            f"Maximum party size is {MAX_PARTY_SIZE}."
        )

    def _setup_contexts(self):
        """Define multi-context workflow for reservation process."""
        contexts = self.define_contexts()

        # ─────────────────────────────────────────────────────────────────────
        # Greeting Context - Entry point
        # ─────────────────────────────────────────────────────────────────────
        greeting = contexts.add_context("greeting")
        greeting.add_step("welcome") \
            .set_text(
                "Welcome to Bobby's Table! I can help you make a new reservation "
                "or look up an existing one. What would you like to do?"
            ) \
            .set_step_criteria("Customer indicates their intent") \
            .set_valid_steps(["next"])
        greeting.add_step("ready") \
            .set_text("How can I help you today?") \
            .set_functions(["start_new_reservation", "lookup_reservation"])

        # ─────────────────────────────────────────────────────────────────────
        # New Reservation Context - Collect all reservation details
        # Single step with ALL collection functions - AI decides which to call
        # ─────────────────────────────────────────────────────────────────────
        new_res = contexts.add_context("new_reservation")
        new_res.add_step("collect") \
            .set_text("Let's get your reservation details.") \
            .set_step_criteria("All reservation details have been collected") \
            .set_functions([
                "set_reservation_name",
                "set_party_size",
                "set_reservation_date",
                "set_reservation_time",
                "set_phone_number",
                "set_special_requests",
                "check_availability",
                "cancel_flow"
            ])

        # ─────────────────────────────────────────────────────────────────────
        # Confirmation Context - Review and confirm
        # ─────────────────────────────────────────────────────────────────────
        confirm = contexts.add_context("confirmation")
        confirm.add_step("confirm") \
            .set_text("Please review your reservation details.") \
            .set_functions(["confirm_reservation", "cancel_flow"])

        # ─────────────────────────────────────────────────────────────────────
        # Manage Context - Lookup, modify, or cancel existing reservations
        # ─────────────────────────────────────────────────────────────────────
        manage = contexts.add_context("manage")
        manage.add_step("found") \
            .set_text("I found your reservation. Would you like to modify or cancel it?") \
            .set_functions(["modify_reservation", "cancel_existing_reservation", "cancel_flow"])

    def _setup_functions(self):
        """Define SWAIG functions for reservation workflow."""

        # ─────────────────────────────────────────────────────────────────────
        # Start New Reservation
        # ─────────────────────────────────────────────────────────────────────
        @self.tool(
            name="start_new_reservation",
            description="Start making a new reservation. Use when customer wants to book a table. After this, collect: name, party size, date, time, phone, then special requests."
        )
        def start_new_reservation(args: dict, raw_data: dict = None) -> SwaigFunctionResult:
            return (
                SwaigFunctionResult("Wonderful! Let's get you a table. May I have the name for the reservation?")
                .swml_change_context("new_reservation")
                .update_global_data({"pending_reservation": {}})
            )

        # ─────────────────────────────────────────────────────────────────────
        # Set Reservation Name
        # ─────────────────────────────────────────────────────────────────────
        @self.tool(
            name="set_reservation_name",
            description="Record the guest's name for the reservation. After setting name, ask for party size.",
            parameters={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The name for the reservation"
                    }
                },
                "required": ["name"]
            }
        )
        def set_reservation_name(args: dict, raw_data: dict = None) -> SwaigFunctionResult:
            name = args.get("name", "")
            raw_data = raw_data or {}
            global_data = raw_data.get("global_data", {})
            pending = global_data.get("pending_reservation", {})

            pending["name"] = name
            global_data["pending_reservation"] = pending

            return (
                SwaigFunctionResult(f"Thank you, {name}. How many guests will be joining us?")
                .update_global_data(global_data)
            )

        # ─────────────────────────────────────────────────────────────────────
        # Set Party Size
        # ─────────────────────────────────────────────────────────────────────
        @self.tool(
            name="set_party_size",
            description="Record the number of guests for the reservation. After setting party size, ask for date.",
            parameters={
                "type": "object",
                "properties": {
                    "party_size": {
                        "type": "integer",
                        "description": "Number of guests",
                        "minimum": 1,
                        "maximum": MAX_PARTY_SIZE
                    }
                },
                "required": ["party_size"]
            }
        )
        def set_party_size(args: dict, raw_data: dict = None) -> SwaigFunctionResult:
            party_size = args.get("party_size", 2)
            raw_data = raw_data or {}
            global_data = raw_data.get("global_data", {})
            pending = global_data.get("pending_reservation", {})

            if party_size > MAX_PARTY_SIZE:
                return SwaigFunctionResult(
                    f"I'm sorry, we can only accommodate parties up to {MAX_PARTY_SIZE}. "
                    "For larger groups, please call us directly."
                )

            pending["party_size"] = party_size
            global_data["pending_reservation"] = pending

            return (
                SwaigFunctionResult(f"Party of {party_size}, got it. What date would you like to dine with us?")
                .update_global_data(global_data)
            )

        # ─────────────────────────────────────────────────────────────────────
        # Set Reservation Date
        # ─────────────────────────────────────────────────────────────────────
        @self.tool(
            name="set_reservation_date",
            description="Record the date for the reservation. Convert natural language like 'tomorrow', 'next Friday', 'January 5th' to YYYY-MM-DD format before calling. After setting date, ask for time.",
            parameters={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "The date in YYYY-MM-DD format (e.g., 2025-01-15). Convert 'tomorrow' to actual date."
                    }
                },
                "required": ["date"]
            }
        )
        def set_reservation_date(args: dict, raw_data: dict = None) -> SwaigFunctionResult:
            date = args.get("date", "")
            raw_data = raw_data or {}
            global_data = raw_data.get("global_data", {})
            pending = global_data.get("pending_reservation", {})

            pending["date"] = date
            global_data["pending_reservation"] = pending

            # Check overall availability for the date
            available_slots = []
            for slot in TIME_SLOTS:
                avail = get_slot_availability(date, slot)
                if avail["available"]:
                    available_slots.append(slot)

            if not available_slots:
                return (
                    SwaigFunctionResult(
                        f"I'm sorry, we're fully booked on {date}. Would you like to try a different date?"
                    )
                    .update_global_data(global_data)
                )

            slots_display = ", ".join(available_slots)
            return (
                SwaigFunctionResult(
                    f"We have availability on {date}. "
                    f"Available times are: {slots_display}. What time would you prefer?"
                )
                .update_global_data(global_data)
            )

        # ─────────────────────────────────────────────────────────────────────
        # Set Reservation Time
        # ─────────────────────────────────────────────────────────────────────
        @self.tool(
            name="set_reservation_time",
            description="Record the time slot for the reservation. Convert '7pm' to '19:00' format. After setting time, ask for phone number.",
            parameters={
                "type": "object",
                "properties": {
                    "time": {
                        "type": "string",
                        "description": "The time slot in 24h format: 17:00, 18:00, 19:00, 20:00, or 21:00",
                        "enum": TIME_SLOTS
                    }
                },
                "required": ["time"]
            }
        )
        def set_reservation_time(args: dict, raw_data: dict = None) -> SwaigFunctionResult:
            time_slot = args.get("time", "")
            raw_data = raw_data or {}
            global_data = raw_data.get("global_data", {})
            pending = global_data.get("pending_reservation", {})
            date = pending.get("date", "")

            if time_slot not in TIME_SLOTS:
                return SwaigFunctionResult(
                    f"I'm sorry, that's not a valid time slot. "
                    f"We have openings at: {', '.join(TIME_SLOTS)}."
                )

            avail = get_slot_availability(date, time_slot)
            if not avail["available"]:
                # Find alternative times
                alternatives = [s for s in TIME_SLOTS if get_slot_availability(date, s)["available"]]
                if alternatives:
                    return SwaigFunctionResult(
                        f"I'm sorry, {time_slot} is fully booked. "
                        f"We have availability at: {', '.join(alternatives)}. Would you like one of those?"
                    )
                else:
                    return SwaigFunctionResult(
                        f"I'm sorry, we're fully booked on {date}. Would you like to try a different date?"
                    )

            pending["time"] = time_slot
            global_data["pending_reservation"] = pending

            return (
                SwaigFunctionResult(f"Great, {time_slot} is available! May I have a phone number for the reservation?")
                .update_global_data(global_data)
            )

        # ─────────────────────────────────────────────────────────────────────
        # Set Phone Number
        # ─────────────────────────────────────────────────────────────────────
        @self.tool(
            name="set_phone_number",
            description="Record the phone number for the reservation. After setting phone, ask about special requests.",
            parameters={
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "The phone number for the reservation in e.164 format"
                    }
                },
                "required": ["phone"]
            }
        )
        def set_phone_number(args: dict, raw_data: dict = None) -> SwaigFunctionResult:
            phone = args.get("phone", "")
            raw_data = raw_data or {}
            global_data = raw_data.get("global_data", {})
            pending = global_data.get("pending_reservation", {})

            pending["phone"] = phone
            global_data["pending_reservation"] = pending

            return (
                SwaigFunctionResult(
                    "Perfect! Any special requests or occasions we should know about? "
                    "For example, a birthday, anniversary, dietary restrictions, or seating preferences?"
                )
                .update_global_data(global_data)
            )

        # ─────────────────────────────────────────────────────────────────────
        # Set Special Requests
        # ─────────────────────────────────────────────────────────────────────
        @self.tool(
            name="set_special_requests",
            description="Record any special requests for the reservation. Call this even if customer says 'none' or 'no'. This completes the collection and shows confirmation.",
            parameters={
                "type": "object",
                "properties": {
                    "requests": {
                        "type": "string",
                        "description": "Special requests or notes. Use empty string if none."
                    }
                },
                "required": []
            }
        )
        def set_special_requests(args: dict, raw_data: dict = None) -> SwaigFunctionResult:
            requests = args.get("requests", "")
            raw_data = raw_data or {}
            global_data = raw_data.get("global_data", {})
            pending = global_data.get("pending_reservation", {})

            pending["special_requests"] = requests if requests else ""
            global_data["pending_reservation"] = pending

            # Build confirmation summary
            name = pending.get("name", "Guest")
            party_size = pending.get("party_size", 0)
            date = pending.get("date", "")
            time_slot = pending.get("time", "")
            phone = pending.get("phone", "")

            summary = (
                f"Let me confirm your reservation: "
                f"{name}, party of {party_size}, on {date} at {time_slot}. "
                f"Phone: {phone}."
            )
            if requests:
                summary += f" Special requests: {requests}."
            summary += " Is this correct?"

            return (
                SwaigFunctionResult(summary)
                .swml_change_context("confirmation")
                .update_global_data(global_data)
            )

        # ─────────────────────────────────────────────────────────────────────
        # Check Availability
        # ─────────────────────────────────────────────────────────────────────
        @self.tool(
            name="check_availability",
            description="Check availability for a specific date and time.",
            parameters={
                "type": "object",
                "properties": {
                    "date": {
                        "type": "string",
                        "description": "The date to check (YYYY-MM-DD)"
                    },
                    "time": {
                        "type": "string",
                        "description": "The time slot to check (optional)",
                        "enum": TIME_SLOTS
                    }
                },
                "required": ["date"]
            }
        )
        def check_availability(args: dict, raw_data: dict = None) -> SwaigFunctionResult:
            date = args.get("date", "")
            time_slot = args.get("time")

            if time_slot:
                avail = get_slot_availability(date, time_slot)
                if avail["available"]:
                    return SwaigFunctionResult(
                        f"Yes, {time_slot} on {date} is available with {avail['remaining']} spots remaining."
                    )
                else:
                    return SwaigFunctionResult(
                        f"I'm sorry, {time_slot} on {date} is fully booked."
                    )
            else:
                available_slots = []
                for slot in TIME_SLOTS:
                    avail = get_slot_availability(date, slot)
                    if avail["available"]:
                        available_slots.append(f"{slot} ({avail['remaining']} spots)")

                if available_slots:
                    return SwaigFunctionResult(
                        f"On {date}, we have availability at: {', '.join(available_slots)}."
                    )
                else:
                    return SwaigFunctionResult(
                        f"I'm sorry, we're fully booked on {date}."
                    )

        # ─────────────────────────────────────────────────────────────────────
        # Confirm Reservation
        # ─────────────────────────────────────────────────────────────────────
        @self.tool(
            name="confirm_reservation",
            description="Finalize and confirm the reservation."
        )
        def confirm_reservation(args: dict, raw_data: dict = None) -> SwaigFunctionResult:
            raw_data = raw_data or {}
            global_data = raw_data.get("global_data", {})
            pending = global_data.get("pending_reservation", {})

            # Validate required fields
            required = ["name", "party_size", "date", "time", "phone"]
            missing = [f for f in required if not pending.get(f)]
            if missing:
                return SwaigFunctionResult(
                    f"I'm missing some information: {', '.join(missing)}. Let's go back and complete those."
                )

            # Check availability one more time
            avail = get_slot_availability(pending["date"], pending["time"])
            if not avail["available"]:
                return SwaigFunctionResult(
                    "I'm sorry, that time slot was just taken. Let me check what else is available."
                )

            # Create the reservation
            confirmation_number = generate_confirmation_number()
            reservation = {
                "id": confirmation_number,
                "name": pending["name"],
                "party_size": pending["party_size"],
                "date": pending["date"],
                "time": pending["time"],
                "phone": pending["phone"],
                "special_requests": pending.get("special_requests", ""),
                "created_at": datetime.utcnow().isoformat(),
                "status": "confirmed"
            }

            # Book the slot and save reservation
            book_slot(pending["date"], pending["time"], confirmation_number)
            RESERVATIONS[confirmation_number] = reservation

            # Clear pending reservation
            global_data["pending_reservation"] = {}
            global_data["last_reservation_id"] = confirmation_number

            # Use say_digits for TTS-friendly pronunciation
            spoken_number = say_digits(confirmation_number)
            result = SwaigFunctionResult(
                f"Your reservation is confirmed! "
                f"{pending['name']}, party of {pending['party_size']}, "
                f"on {pending['date']} at {pending['time']}. "
                f"Your confirmation number is {spoken_number}. We look forward to seeing you!"
            )
            result.update_global_data(global_data)

            # Send event to frontend
            result.swml_user_event({
                "type": "reservation_confirmed",
                "reservation": reservation
            })

            return result

        # ─────────────────────────────────────────────────────────────────────
        # Lookup Reservation
        # ─────────────────────────────────────────────────────────────────────
        @self.tool(
            name="lookup_reservation",
            description="Look up an existing reservation by phone number or name.",
            parameters={
                "type": "object",
                "properties": {
                    "phone": {
                        "type": "string",
                        "description": "Phone number to search"
                    },
                    "name": {
                        "type": "string",
                        "description": "Name to search"
                    }
                },
                "required": []
            }
        )
        def lookup_reservation(args: dict, raw_data: dict = None) -> SwaigFunctionResult:
            phone = args.get("phone", "")
            name = args.get("name", "")
            raw_data = raw_data or {}
            global_data = raw_data.get("global_data", {})

            if not phone and not name:
                return (
                    SwaigFunctionResult(
                        "I can look up your reservation by phone number or name. Which would you like to provide?"
                    )
                    .swml_change_context("manage")
                )

            # Search for matching reservations
            matches = []
            for res_id, res in RESERVATIONS.items():
                if res["status"] != "confirmed":
                    continue
                if phone and phone in res.get("phone", ""):
                    matches.append(res)
                elif name and name.lower() in res.get("name", "").lower():
                    matches.append(res)

            if not matches:
                return SwaigFunctionResult(
                    "I couldn't find a reservation with that information. "
                    "Would you like to try different details or make a new reservation?"
                )

            if len(matches) == 1:
                res = matches[0]
                global_data["found_reservation_id"] = res["id"]
                return (
                    SwaigFunctionResult(
                        f"I found your reservation: {res['name']}, party of {res['party_size']}, "
                        f"on {res['date']} at {res['time']}. "
                        "Would you like to modify or cancel this reservation?"
                    )
                    .swml_change_context("manage")
                    .update_global_data(global_data)
                )

            # Multiple matches
            res_list = "; ".join(
                f"{r['name']} on {r['date']} at {r['time']}"
                for r in matches[:3]
            )
            return SwaigFunctionResult(
                f"I found multiple reservations: {res_list}. "
                "Could you provide more details to help me find the right one?"
            )

        # ─────────────────────────────────────────────────────────────────────
        # Modify Reservation
        # ─────────────────────────────────────────────────────────────────────
        @self.tool(
            name="modify_reservation",
            description="Modify an existing reservation.",
            parameters={
                "type": "object",
                "properties": {
                    "party_size": {"type": "integer", "description": "New party size"},
                    "date": {"type": "string", "description": "New date (YYYY-MM-DD)"},
                    "time": {"type": "string", "description": "New time slot", "enum": TIME_SLOTS},
                    "special_requests": {"type": "string", "description": "Updated special requests"}
                },
                "required": []
            }
        )
        def modify_reservation(args: dict, raw_data: dict = None) -> SwaigFunctionResult:
            raw_data = raw_data or {}
            global_data = raw_data.get("global_data", {})
            res_id = global_data.get("found_reservation_id")

            if not res_id or res_id not in RESERVATIONS:
                return SwaigFunctionResult(
                    "I need to look up your reservation first. "
                    "Can you provide your phone number or name?"
                )

            res = RESERVATIONS[res_id]
            old_date = res["date"]
            old_time = res["time"]

            # Check if date/time is changing
            new_date = args.get("date", old_date)
            new_time = args.get("time", old_time)

            if new_date != old_date or new_time != old_time:
                # Check new slot availability
                avail = get_slot_availability(new_date, new_time)
                if not avail["available"]:
                    return SwaigFunctionResult(
                        f"I'm sorry, {new_time} on {new_date} is not available. "
                        "Would you like to try a different time?"
                    )
                # Release old slot and book new
                release_slot(old_date, old_time, res_id)
                book_slot(new_date, new_time, res_id)
                res["date"] = new_date
                res["time"] = new_time

            if "party_size" in args:
                res["party_size"] = args["party_size"]
            if "special_requests" in args:
                res["special_requests"] = args["special_requests"]

            result = SwaigFunctionResult(
                f"Your reservation has been updated: {res['name']}, party of {res['party_size']}, "
                f"on {res['date']} at {res['time']}. Is there anything else?"
            )
            result.swml_user_event({
                "type": "reservation_modified",
                "reservation": res
            })
            return result

        # ─────────────────────────────────────────────────────────────────────
        # Cancel Existing Reservation
        # ─────────────────────────────────────────────────────────────────────
        @self.tool(
            name="cancel_existing_reservation",
            description="Cancel an existing reservation."
        )
        def cancel_existing_reservation(args: dict, raw_data: dict = None) -> SwaigFunctionResult:
            raw_data = raw_data or {}
            global_data = raw_data.get("global_data", {})
            res_id = global_data.get("found_reservation_id")

            if not res_id or res_id not in RESERVATIONS:
                return SwaigFunctionResult(
                    "I need to look up your reservation first. "
                    "Can you provide your phone number or name?"
                )

            res = RESERVATIONS[res_id]
            res["status"] = "cancelled"
            release_slot(res["date"], res["time"], res_id)

            global_data["found_reservation_id"] = None

            result = SwaigFunctionResult(
                f"Your reservation for {res['name']} on {res['date']} at {res['time']} "
                "has been cancelled. Is there anything else I can help with?"
            )
            result.update_global_data(global_data)
            result.swml_user_event({
                "type": "reservation_cancelled",
                "reservation_id": res_id
            })
            result.swml_change_context("greeting")
            return result

        # ─────────────────────────────────────────────────────────────────────
        # Cancel Flow (return to greeting)
        # ─────────────────────────────────────────────────────────────────────
        @self.tool(
            name="cancel_flow",
            description="Cancel the current action and return to the main menu."
        )
        def cancel_flow(args: dict, raw_data: dict = None) -> SwaigFunctionResult:
            return (
                SwaigFunctionResult(
                    "No problem! Is there anything else I can help you with?"
                )
                .swml_change_context("greeting")
                .update_global_data({"pending_reservation": {}, "found_reservation_id": None})
            )

    def on_swml_request(self, request_data, callback_path, request=None):
        """Configure dynamic settings for each request."""
        self.set_param("end_of_speech_timeout", 700)

        base_url = self.get_full_url(include_auth=False)

        if base_url:
            self.set_param("video_idle_file", f"{base_url}/sigmond_pc_idle.mp4")
            self.set_param("video_talking_file", f"{base_url}/sigmond_pc_talking.mp4")

        # Optional post-prompt URL from environment
        post_prompt_url = os.environ.get("POST_PROMPT_URL")
        if post_prompt_url:
            self.set_post_prompt(
                "Summarize the reservation call including: "
                "whether a reservation was made, modified, or cancelled; "
                "the guest name, party size, date and time if applicable; "
                "and any special requests mentioned."
            )
            self.set_post_prompt_url(post_prompt_url)

        self.add_language(
            name="English",
            code="en-US",
            voice="elevenlabs.adam"
        )

        self.add_hints([
            "Bobby's Table",
            "reservation",
            "party of",
            "five PM", "six PM", "seven PM", "eight PM", "nine PM",
            "17:00", "18:00", "19:00", "20:00", "21:00"
        ])

        return super().on_swml_request(request_data, callback_path, request)


# ═══════════════════════════════════════════════════════════════════════════════
# Server Creation
# ═══════════════════════════════════════════════════════════════════════════════
# The create_server function sets up the FastAPI application with all routes
# and middleware.

def create_server(port=None):
    """
    Create AgentServer with static file mounting and API endpoints.

    This function:
    1. Creates an AgentServer instance
    2. Registers the agent at its route
    3. Serves static files from the web/ directory
    4. Adds custom API endpoints (/get_token, /health, /api/reservations)
    5. Registers startup event for SWML handler setup

    Returns:
        AgentServer instance with everything configured
    """
    # Create the server
    server = AgentServer(host=HOST, port=port or PORT)

    # Create and register the agent
    agent = ReservationAgent()
    server.register(agent, "/bobbystable")

    # Serve static files from web/ directory (index.html, app.js, styles.css)
    web_dir = Path(__file__).parent / "web"
    if web_dir.exists():
        server.serve_static_files(str(web_dir))

    # ─────────────────────────────────────────────────────────────────────────
    # Health Check Endpoint
    # Required for Dokku/Heroku deployments to verify the app is running
    # ─────────────────────────────────────────────────────────────────────────
    @server.app.get("/health")
    def health_check():
        """Health check endpoint for deployment verification."""
        return {"status": "healthy", "agent": "example"}

    @server.app.get("/ready")
    def ready_check():
        """Readiness check - verifies SWML handler is configured."""
        if swml_handler_info.get("address"):
            return {"status": "ready", "address": swml_handler_info["address"]}
        return {"status": "initializing"}

    # ─────────────────────────────────────────────────────────────────────────
    # Token Generation Endpoint
    # This is how web clients get authentication tokens for WebRTC calls
    # ─────────────────────────────────────────────────────────────────────────
    @server.app.get("/get_token")
    def get_token():
        """
        Generate a guest token for the web client.

        This endpoint:
        1. Validates SignalWire credentials are configured
        2. Verifies SWML handler is registered
        3. Creates a scoped guest token via SignalWire API
        4. Returns token and destination address

        The frontend uses this to initialize the SignalWire client and dial.
        """
        sw_host = get_signalwire_host()
        project = os.getenv("SIGNALWIRE_PROJECT_ID", "")
        token = os.getenv("SIGNALWIRE_TOKEN", "")

        # Validate configuration
        if not all([sw_host, project, token]):
            return {"error": "SignalWire credentials not configured"}, 500

        if not swml_handler_info.get("address_id"):
            return {"error": "SWML handler not configured yet"}, 500

        auth = (project, token)

        try:
            # Create guest token with 24-hour expiry
            # Token is scoped to only allow calling our specific address
            expire_at = int(time.time()) + 3600 * 24  # 24 hours

            guest_resp = requests.post(
                f"https://{sw_host}/api/fabric/guests/tokens",
                json={
                    "allowed_addresses": [swml_handler_info["address_id"]],
                    "expire_at": expire_at
                },
                auth=auth,
                headers={"Content-Type": "application/json", "Accept": "application/json"}
            )
            guest_resp.raise_for_status()
            guest_token = guest_resp.json().get("token", "")

            # Return token and the address to dial
            return {
                "token": guest_token,
                "address": swml_handler_info["address"]
            }
        except Exception as e:
            logger.error(f"Token request failed: {e}")
            return {"error": str(e)}, 500

    # ─────────────────────────────────────────────────────────────────────────
    # Debug Endpoint (optional - remove in production if desired)
    # ─────────────────────────────────────────────────────────────────────────
    @server.app.get("/get_resource_info")
    def get_resource_info():
        """Return SWML handler info for debugging."""
        return swml_handler_info

    # ─────────────────────────────────────────────────────────────────────────
    # Config Endpoint
    # ─────────────────────────────────────────────────────────────────────────
    @server.app.get("/api/config")
    def get_config():
        """Return public configuration for the frontend."""
        phone_number = os.getenv("PHONE_NUMBER", "")
        return {
            "phone_number": phone_number if phone_number else None,
            "restaurant_name": "Bobby's Table"
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Reservation API Endpoints
    # ─────────────────────────────────────────────────────────────────────────
    @server.app.get("/api/reservations")
    def get_reservations():
        """Return all reservations grouped by date, sorted by time."""
        grouped = {}
        for res_id, res in RESERVATIONS.items():
            if res["status"] == "confirmed":
                date = res["date"]
                if date not in grouped:
                    grouped[date] = []
                grouped[date].append(res)

        # Sort each date's reservations by time
        for date in grouped:
            grouped[date].sort(key=lambda x: x["time"])

        # Sort dates
        sorted_grouped = dict(sorted(grouped.items()))

        return {
            "reservations": sorted_grouped,
            "total_count": sum(len(v) for v in grouped.values())
        }

    @server.app.get("/api/availability/{date}")
    def get_availability(date: str):
        """Return availability for all time slots on a date."""
        if date not in AVAILABILITY:
            # Initialize if not exists
            return {
                slot: {"available": MAX_PER_SLOT, "total": MAX_PER_SLOT}
                for slot in TIME_SLOTS
            }

        return {
            slot: {
                "available": data["max"] - data["booked"],
                "total": data["max"]
            }
            for slot, data in AVAILABILITY[date].items()
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Startup: Register SWML handler
    # ─────────────────────────────────────────────────────────────────────────
    setup_swml_handler()

    return server


# ═══════════════════════════════════════════════════════════════════════════════
# Module-Level Exports
# ═══════════════════════════════════════════════════════════════════════════════
# These are required for gunicorn to find the application.

# Create server instance
server = create_server()

# Expose the FastAPI app for gunicorn
# Usage in Procfile: gunicorn app:app --bind 0.0.0.0:$PORT ...
app = server.app


# ═══════════════════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════════════════
# This runs when executing the script directly (not through gunicorn).

if __name__ == "__main__":
    server.run()
