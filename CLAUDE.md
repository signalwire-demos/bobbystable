# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Bobby's Table - a restaurant reservation system with a SignalWire AI agent backend (Python/FastAPI) and vanilla JavaScript WebRTC frontend. Reservations are made via phone calls and displayed on a web dashboard.

## Commands

```bash
# Local development (activate venv first or run in container)
python app.py

# Production (used by Procfile)
gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --worker-class uvicorn.workers.UvicornWorker
```

## Architecture

**Backend (`app.py`):**
- Uses `signalwire-agents` SDK with `AgentBase` and `AgentServer` classes
- Multi-context workflow pattern (from `lab2_5_contexts.py`) with `define_contexts()`, `add_context()`, `add_step()`
- Contexts: `greeting` → `new_reservation` → `confirmation`, with `manage` for existing reservations
- SWAIG functions defined with `@self.tool()` decorator for each step
- Context switching via `.swml_change_context()`
- State persistence via `global_data` and `.update_global_data()`
- In-memory storage: `RESERVATIONS` dict and `AVAILABILITY` tracking

**Reservation Data Model:**
```python
{
    "id": "res_abc123",
    "name": "John Smith",
    "party_size": 4,
    "date": "2025-01-15",     # YYYY-MM-DD
    "time": "18:00",          # 24-hour format
    "phone": "+15551234567",
    "special_requests": "Anniversary dinner",
    "status": "confirmed"
}
```

**Time Slots:** 17:00, 18:00, 19:00, 20:00, 21:00 (5 PM - 9 PM)
**Max per slot:** 5 reservations

**Frontend (`web/`):**
- Static files served by AgentServer
- Displays reservations grouped by date
- Real-time updates via `reservation_confirmed/modified/cancelled` user events

**Key endpoints:**
- `GET /get_token` - Returns `{token, address}` for WebRTC client
- `GET /api/reservations` - All reservations grouped by date
- `GET /api/availability/{date}` - Slot availability for a date
- `GET /health` - Health check
- `POST /bobbystable` - SWML endpoint (called by SignalWire)

## Environment Variables

Required:
- `SIGNALWIRE_SPACE_NAME` - Your SignalWire space
- `SIGNALWIRE_PROJECT_ID` - Project ID
- `SIGNALWIRE_TOKEN` - API token

URL detection (one required for SWML callbacks):
- `SWML_PROXY_URL_BASE` - Set for local dev with ngrok
- `APP_URL` - Auto-set on Dokku/Heroku

Optional:
- `AGENT_NAME` - Handler name (default: "bobbystable")
- `SWML_BASIC_AUTH_USER/PASSWORD` - Secures SWML endpoint

## Key Patterns

**Context/Step Definition:**
```python
contexts = self.define_contexts()
greeting = contexts.add_context("greeting")
greeting.add_step("welcome") \
    .set_text("Welcome to Bobby's Table!") \
    .set_step_criteria("Customer indicates intent") \
    .set_functions(["start_new_reservation", "lookup_reservation"])
```

**SWAIG Function with Context Switch:**
```python
@self.tool(name="start_new_reservation", description="...")
def start_new_reservation(args, raw_data):
    return (
        SwaigFunctionResult("Let's get you a table...")
        .swml_change_context("new_reservation")
        .update_global_data({"pending_reservation": {}})
    )
```

## Deployment

Configured for Dokku with `.dokku/` config files. Health checks via `/health` and `/ready` endpoints.
