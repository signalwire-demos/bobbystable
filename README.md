# Bobby's Table

A voice-powered restaurant reservation system built with SignalWire AI. Customers call to make reservations through natural conversation, while staff view and manage bookings through a real-time web dashboard.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                             │
│    Customer calls  ───►  AI Agent  ───►  Reservation Created/Modified       │
│                                                                             │
│                              │                                              │
│                              ▼                                              │
│                       Web Dashboard                                         │
│                    (real-time updates)                                      │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Features

- **Voice Reservations** - Natural conversation flow to book tables
- **Lookup and Manage** - Find, modify, or cancel existing reservations by phone or name
- **Smart Availability** - Time slot management with capacity limits
- **Real-time Dashboard** - Live updates when reservations change
- **Multi-context AI** - Guided conversation prevents errors
- **In-memory Storage** - Simple deployment, no database required

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              SIGNALWIRE                                 │
│  ┌─────────────┐         ┌─────────────┐         ┌─────────────┐        │
│  │   Phone     │         │   WebRTC    │         │    SWML     │        │
│  │   Network   │────────►│   Gateway   │────────►│   Handler   │        │
│  └─────────────┘         └─────────────┘         └──────┬──────┘        │
└─────────────────────────────────────────────────────────┼───────────────┘
                                                          │
                                                          ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          BOBBY'S TABLE SERVER                           │
│                                                                         │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                      ReservationAgent                              │ │
│  │  ┌──────────┐    ┌───────────┐    ┌──────────┐    ┌──────────┐     │ │
│  │  │ Greeting │───►│   New     │───►│ Confirm  │    │  Manage  │     │ │
│  │  │ Context  │    │Reservation│    │ Context  │    │ Context  │     │ │
│  │  └──────────┘    │ Context   │    └──────────┘    └──────────┘     │ │
│  │       │          └───────────┘                          ▲          │ │
│  │       └─────────────────────────────────────────────────┘          │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                    │                                    │
│                                    ▼                                    │
│  ┌─────────────────┐    ┌─────────────────┐    ┌───────────────────┐    │
│  │  RESERVATIONS   │    │  AVAILABILITY   │    │   API Routes      │    │
│  │    (dict)       │    │    (dict)       │    │  /api/config      │    │
│  │                 │    │                 │    │  /api/reservations│    │
│  └─────────────────┘    └─────────────────┘    └───────────────────┘    │
│                                                          │              │
└──────────────────────────────────────────────────────────┼──────────────┘
                                                           │
                                                           ▼
┌────────────────────────────────────────────────────────────────────────┐
│                           WEB DASHBOARD                                │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  ┌─────────┐  ┌──────────────────────────────────────────────┐  │   │
│  │  │  Video  │  │              Reservations                    │  │   │
│  │  │  Call   │  │  ┌─────────────────────────────────────────┐ │  │   │
│  │  │         │  │  │ Today                                   │ │  │   │
│  │  ├─────────┤  │  │  5:00 PM  John Smith    Party of 4      │ │  │   │
│  │  │ Connect │  │  │  7:00 PM  Jane Doe      Party of 2      │ │  │   │
│  │  └─────────┘  │  └─────────────────────────────────────────┘ │  │   │
│  │               │  ┌─────────────────────────────────────────┐ │  │   │
│  │  Activity Log │  │ Tomorrow                                │ │  │   │
│  │  ───────────  │  │  6:00 PM  Bob Wilson    Party of 6      │ │  │   │
│  │  Connected... │  └─────────────────────────────────────────┘ │  │   │
│  │  New reserv...│                                              │  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────┘
```

## Conversation Flow

### New Reservation Flow

```
                                    START
                                      │
                                      ▼
                        ┌─────────────────────────┐
                        │     GREETING CONTEXT    │
                        │                         │
                        │  "Welcome to Bobby's    │
                        │   Table! Make a new     │
                        │   reservation or look   │
                        │   up an existing one?"  │
                        └───────────┬─────────────┘
                                    │
                                    │ "I'd like to make
                                    │  a reservation"
                                    ▼
                     ┌──────────────────────────┐
                     │  NEW RESERVATION CONTEXT │
                     │                          │
                     │  Collect in order:       │
                     │  1. Name                 │
                     │  2. Party size (1-20)    │
                     │  3. Date                 │
                     │  4. Time slot            │
                     │  5. Phone number         │
                     │  6. Special requests     │
                     └────────────┬─────────────┘
                                  │
                                  ▼
                     ┌──────────────────────────┐
                     │  CONFIRMATION CONTEXT    │
                     │                          │
                     │  "Your reservation:      │
                     │   John, party of 4,      │
                     │   Jan 15 at 7:00 PM.     │
                     │   Confirm?"              │
                     │                          │
                     │  ┌─────────┐ ┌────────┐  │
                     │  │ Confirm │ │ Cancel │  │
                     │  └────┬────┘ └───┬────┘  │
                     └───────┼──────────┼───────┘
                             │          │
                             ▼          ▼
                     ┌──────────────┐  Back to
                     │ RESERVATION  │  Greeting
                     │   SAVED      │
                     │              │
                     │ Real-time    │
                     │ update sent  │
                     │ to dashboard │
                     └──────────────┘
```

### Lookup and Manage Flow

```
                        ┌─────────────────────────┐
                        │     GREETING CONTEXT    │
                        │                         │
                        │  "Welcome to Bobby's    │
                        │   Table!"               │
                        └───────────┬─────────────┘
                                    │
                                    │ "I need to change/cancel
                                    │  my reservation"
                                    ▼
                        ┌─────────────────────────┐
                        │     MANAGE CONTEXT      │
                        │                         │
                        │  lookup_reservation()   │
                        │  - Search by phone OR   │
                        │  - Search by name       │
                        └───────────┬─────────────┘
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
              ▼                     ▼                     ▼
    ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐
    │  NOT FOUND      │   │  MODIFY         │   │  CANCEL         │
    │                 │   │                 │   │                 │
    │  "I couldn't    │   │  Change:        │   │  "Are you sure  │
    │   find that     │   │  - Party size   │   │   you want to   │
    │   reservation"  │   │  - Date         │   │   cancel?"      │
    │                 │   │  - Time         │   │                 │
    │  -> Greeting    │   │  - Requests     │   │  -> Greeting    │
    └─────────────────┘   └────────┬────────┘   └─────────────────┘
                                   │
                                   ▼
                        ┌─────────────────────────┐
                        │  RESERVATION UPDATED    │
                        │                         │
                        │  Real-time update       │
                        │  sent to dashboard      │
                        │                         │
                        │  -> Greeting            │
                        └─────────────────────────┘
```

### Manage Context Functions

| Function | Purpose | Parameters |
|----------|---------|------------|
| `lookup_reservation` | Find existing reservation | `phone` or `name` |
| `modify_reservation` | Update reservation details | `reservation_id`, `party_size`, `date`, `time`, `special_requests` |
| `cancel_reservation` | Cancel a reservation | `reservation_id` |

The manage flow allows customers to:

1. **Lookup by phone**: "I have a reservation under 555-123-4567"
2. **Lookup by name**: "I have a reservation under Smith"
3. **Modify details**: Change party size, date, time, or special requests
4. **Cancel entirely**: Remove the reservation from the system

When a reservation is found, the agent reads back the details and asks what the customer would like to change. All modifications trigger real-time updates to the web dashboard.

## Time Slots and Availability

```
┌───────────────────────────────────────────────────────────────┐
│                     DAILY TIME SLOTS                          │
├───────────────────────────────────────────────────────────────┤
│                                                               │
│   5:00 PM   6:00 PM   7:00 PM   8:00 PM   9:00 PM             │
│   (17:00)   (18:00)   (19:00)   (20:00)   (21:00)             │
│                                                               │
│   ┌─────┐   ┌─────┐   ┌─────┐   ┌─────┐   ┌─────┐             │
│   │#....│   │##...│   │#####│   │##...│   │.....│             │
│   │ 1/5 │   │ 2/5 │   │ 5/5 │   │ 2/5 │   │ 0/5 │             │
│   └─────┘   └─────┘   └─────┘   └─────┘   └─────┘             │
│   4 avail   3 avail   FULL      3 avail   5 avail             │
│                                                               │
│   Maximum 5 reservations per time slot                        │
│   Maximum party size: 20 guests                               │
│                                                               │
└───────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- SignalWire account ([sign up free](https://signalwire.com))

### Installation

```bash
# Clone the repository
git clone <repo-url>
cd bobbystable

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your SignalWire credentials
```

### Configuration

Edit `.env` with your settings:

```bash
# Required - SignalWire credentials
SIGNALWIRE_SPACE_NAME=your-space
SIGNALWIRE_PROJECT_ID=your-project-id
SIGNALWIRE_TOKEN=your-api-token

# Required for local dev - use ngrok or similar
SWML_PROXY_URL_BASE=https://your-ngrok-url.ngrok.io

# Optional - display phone number on website
PHONE_NUMBER=+1-555-123-4567

# Optional - post-call summary webhook
POST_PROMPT_URL=https://your-webhook.com/summary
```

### Running

```bash
# Local development
python app.py

# Production (via Procfile)
gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --worker-class uvicorn.workers.UvicornWorker
```

Open http://localhost:5000 to view the dashboard.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/config` | GET | Returns phone number and restaurant name |
| `/api/reservations` | GET | All reservations grouped by date |
| `/api/availability/{date}` | GET | Slot availability for a specific date |
| `/get_token` | GET | WebRTC authentication token |
| `/health` | GET | Health check |
| `/bobbystable` | POST | SWML webhook (called by SignalWire) |

### Example: Get Reservations

```bash
curl http://localhost:5000/api/reservations
```

```json
{
  "reservations": {
    "2025-01-15": [
      {
        "id": "res_a1b2c3d4",
        "name": "John Smith",
        "party_size": 4,
        "time": "19:00",
        "phone": "+15551234567",
        "special_requests": "Anniversary dinner",
        "status": "confirmed"
      }
    ]
  },
  "total_count": 1
}
```

## Data Model

```
┌─────────────────────────────────────────────────────────────────┐
│                        RESERVATION                              │
├─────────────────────────────────────────────────────────────────┤
│  id                 string      "res_a1b2c3d4"                  │
│  name               string      "John Smith"                    │
│  party_size         integer     4                               │
│  date               string      "2025-01-15"                    │
│  time               string      "19:00"                         │
│  phone              string      "+15551234567"                  │
│  special_requests   string      "Anniversary dinner"            │
│  created_at         string      "2025-01-10T14:30:00Z"          │
│  status             string      "confirmed" | "cancelled"       │
└─────────────────────────────────────────────────────────────────┘
```

## Tech Stack

- **Backend**: Python, FastAPI, SignalWire Agents SDK
- **Frontend**: Vanilla JavaScript, SignalWire WebRTC SDK
- **AI**: SignalWire AI with multi-context SWML
- **Deployment**: Dokku/Heroku compatible

## Project Structure

```
bobbystable/
├── app.py              # Main application (agent + server)
├── web/
│   ├── index.html      # Dashboard UI
│   ├── app.js          # Frontend logic
│   └── styles.css      # Styling
├── .env.example        # Environment template
├── requirements.txt    # Python dependencies
├── Procfile           # Production server config
└── .dokku/            # Deployment configuration
```

## Deployment

The app is configured for Dokku/Heroku deployment:

1. Set environment variables on your platform
2. Push to deploy
3. The app auto-registers its SWML handler with SignalWire on startup

For local development with phone calls, use [ngrok](https://ngrok.com) to expose your local server:

```bash
ngrok http 5000
# Set SWML_PROXY_URL_BASE to the ngrok URL
```

## License

MIT
