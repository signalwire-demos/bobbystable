/**
 * ═══════════════════════════════════════════════════════════════════════════════
 * Bobby's Table - Restaurant Reservation System Frontend
 * ═══════════════════════════════════════════════════════════════════════════════
 *
 * Handles WebRTC connection to the reservation agent and displays
 * reservations in real-time.
 *
 * ═══════════════════════════════════════════════════════════════════════════════
 */

// ─────────────────────────────────────────────────────────────────────────────
// Global State
// ─────────────────────────────────────────────────────────────────────────────

let client = null;
let roomSession = null;
let currentToken = null;
let currentDestination = null;
let isConnected = false;


// ─────────────────────────────────────────────────────────────────────────────
// DOM Element References
// ─────────────────────────────────────────────────────────────────────────────

const videoContainer = document.getElementById('video-container');
const connectBtn = document.getElementById('connect-btn');
const disconnectBtn = document.getElementById('disconnect-btn');
const statusEl = document.getElementById('status');
const eventLogEl = document.getElementById('event-log');
const reservationsContainer = document.getElementById('reservations-container');
const totalReservationsEl = document.getElementById('total-reservations');
const todaysReservationsEl = document.getElementById('todays-reservations');


// ─────────────────────────────────────────────────────────────────────────────
// Connection Functions
// ─────────────────────────────────────────────────────────────────────────────

async function connect() {
    if (isConnected) {
        logEvent('system', 'Already connected');
        return;
    }

    updateStatus('connecting', 'Getting token...');
    logEvent('system', 'Fetching authentication token...');

    try {
        const tokenResp = await fetch('/get_token');
        const tokenData = await tokenResp.json();

        if (tokenData.error) {
            throw new Error(tokenData.error);
        }

        currentToken = tokenData.token;
        currentDestination = tokenData.address;

        logEvent('system', `Token received, destination: ${currentDestination}`);
        updateStatus('connecting', 'Initializing client...');

        client = await window.SignalWire.SignalWire({
            token: currentToken,
            logLevel: 'debug'
        });

        logEvent('system', 'Client initialized');

        // Set up event listeners on the client
        client.on('user_event', (params) => {
            console.log('CLIENT EVENT: user_event', params);
            handleUserEvent(params);
        });

        client.on('calling.user_event', (params) => {
            console.log('CLIENT EVENT: calling.user_event', params);
            handleUserEvent(params);
        });

        client.on('signalwire.event', (params) => {
            console.log('CLIENT EVENT: signalwire.event', params);
            if (params.event_type === 'user_event') {
                handleUserEvent(params.params || params);
            }
        });

        updateStatus('connecting', 'Dialing agent...');

        roomSession = await client.dial({
            to: currentDestination,
            rootElement: videoContainer,
            audio: {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true
            },
            video: true,
            negotiateVideo: true,
            userVariables: {
                userName: 'Web Client',
                interface: 'web-ui',
                timestamp: new Date().toISOString()
            }
        });

        logEvent('system', 'Call initiated, waiting for connection...');

        // Room session event listeners
        roomSession.on('user_event', (params) => {
            console.log('ROOM EVENT: user_event', params);
            handleUserEvent(params);
        });

        roomSession.on('room.joined', () => {
            logEvent('system', 'Connected to Bobby\'s Table');
            updateStatus('connected', 'Connected');
            isConnected = true;
            updateButtons();

            const placeholder = videoContainer.querySelector('.placeholder');
            if (placeholder) {
                placeholder.style.display = 'none';
            }
        });

        roomSession.on('room.left', () => {
            logEvent('system', 'Disconnected from agent');
            handleDisconnect();
        });

        roomSession.on('destroy', () => {
            logEvent('system', 'Session destroyed');
            handleDisconnect();
        });

        await roomSession.start();
        logEvent('system', 'Call started successfully');

    } catch (error) {
        console.error('Connection error:', error);
        logEvent('error', `Connection failed: ${error.message}`);
        updateStatus('error', 'Connection failed');
        handleDisconnect();
    }
}


async function disconnect() {
    if (!isConnected && !roomSession) {
        logEvent('system', 'Not connected');
        return;
    }

    logEvent('system', 'Disconnecting...');
    updateStatus('disconnecting', 'Disconnecting...');

    try {
        if (roomSession) {
            await roomSession.hangup();
        }
    } catch (error) {
        console.error('Disconnect error:', error);
    }

    handleDisconnect();
}


function handleDisconnect() {
    isConnected = false;
    roomSession = null;

    videoContainer.innerHTML = '<div class="placeholder"><img src="sigmond_pc.png" alt="Bobby - Click Connect to start"></div>';

    updateStatus('disconnected', 'Disconnected');
    updateButtons();
}


// ─────────────────────────────────────────────────────────────────────────────
// User Event Handling
// ─────────────────────────────────────────────────────────────────────────────

function handleUserEvent(params) {
    console.log('Processing user event:', params);

    let eventData = params;
    if (params && params.params) {
        eventData = params.params;
    }
    if (params && params.event) {
        eventData = params.event;
    }

    if (!eventData || typeof eventData.type !== 'string') {
        console.log('Skipping non-application event:', params);
        return;
    }

    const internalTypes = ['room.joined', 'room.left', 'member.joined', 'member.left', 'playback.started', 'playback.ended'];
    if (internalTypes.includes(eventData.type)) {
        console.log('Skipping internal event type:', eventData.type);
        return;
    }

    const eventType = eventData.type;

    switch (eventType) {
        case 'reservation_confirmed':
            const res = eventData.reservation;
            logEvent('reservation', `New reservation: ${res.name}, party of ${res.party_size}, ${res.date} at ${res.time}`);
            // Refresh the reservations list
            refreshReservations();
            break;

        case 'reservation_modified':
            const modRes = eventData.reservation;
            logEvent('reservation', `Modified: ${modRes.name}, ${modRes.date} at ${modRes.time}`);
            refreshReservations();
            break;

        case 'reservation_cancelled':
            logEvent('reservation', `Cancelled: ${eventData.reservation_id}`);
            refreshReservations();
            break;

        default:
            console.log('Unknown event type:', eventType, eventData);
            logEvent('event', `Event: ${eventType}`);
    }
}


// ─────────────────────────────────────────────────────────────────────────────
// Reservations Display
// ─────────────────────────────────────────────────────────────────────────────

async function refreshReservations() {
    try {
        const resp = await fetch('/api/reservations');
        const data = await resp.json();

        displayReservations(data.reservations);
        updateStats(data);
    } catch (error) {
        console.error('Failed to fetch reservations:', error);
        logEvent('error', 'Failed to fetch reservations');
    }
}


function displayReservations(reservationsByDate) {
    const container = reservationsContainer;

    // Check if we have any reservations
    const dates = Object.keys(reservationsByDate);
    if (dates.length === 0) {
        container.innerHTML = `
            <div class="no-reservations">
                <p>No reservations yet.</p>
                <p class="hint">Connect and make a reservation via phone!</p>
            </div>
        `;
        return;
    }

    // Build HTML for reservations grouped by date
    let html = '';
    for (const date of dates) {
        const reservations = reservationsByDate[date];
        const formattedDate = formatDate(date);

        html += `
            <div class="date-group">
                <h3 class="date-header">${formattedDate}</h3>
                <div class="reservations-list">
        `;

        for (const res of reservations) {
            const formattedTime = formatTime(res.time);
            html += `
                <div class="reservation-card">
                    <div class="reservation-time">${formattedTime}</div>
                    <div class="reservation-details">
                        <div class="reservation-name">${escapeHtml(res.name)}</div>
                        <div class="reservation-party">Party of ${res.party_size}</div>
                        ${res.phone ? `<div class="reservation-phone">${escapeHtml(res.phone)}</div>` : ''}
                        ${res.special_requests ? `<div class="reservation-special">${escapeHtml(res.special_requests)}</div>` : ''}
                    </div>
                    <div class="reservation-id">${res.id}</div>
                </div>
            `;
        }

        html += `
                </div>
            </div>
        `;
    }

    container.innerHTML = html;
}


function updateStats(data) {
    totalReservationsEl.textContent = data.total_count || 0;

    // Count today's reservations
    const today = new Date().toISOString().split('T')[0];
    const todaysRes = data.reservations[today] || [];
    todaysReservationsEl.textContent = todaysRes.length;
}


// ─────────────────────────────────────────────────────────────────────────────
// UI Helper Functions
// ─────────────────────────────────────────────────────────────────────────────

function updateStatus(state, text) {
    statusEl.className = `status ${state}`;
    statusEl.querySelector('.status-text').textContent = text;
}


function updateButtons() {
    connectBtn.disabled = isConnected;
    disconnectBtn.disabled = !isConnected;
}


function logEvent(type, message) {
    const entry = document.createElement('div');
    entry.className = `log-entry ${type}`;

    const timestamp = new Date().toLocaleTimeString();
    entry.innerHTML = `<span class="log-time">${timestamp}</span> ${escapeHtml(message)}`;

    eventLogEl.appendChild(entry);
    eventLogEl.scrollTop = eventLogEl.scrollHeight;

    // Keep only last 50 entries
    while (eventLogEl.children.length > 50) {
        eventLogEl.removeChild(eventLogEl.firstChild);
    }
}


function formatDate(dateStr) {
    const date = new Date(dateStr + 'T00:00:00');
    const today = new Date();
    const tomorrow = new Date(today);
    tomorrow.setDate(tomorrow.getDate() + 1);

    const todayStr = today.toISOString().split('T')[0];
    const tomorrowStr = tomorrow.toISOString().split('T')[0];

    if (dateStr === todayStr) {
        return 'Today';
    } else if (dateStr === tomorrowStr) {
        return 'Tomorrow';
    } else {
        return date.toLocaleDateString('en-US', {
            weekday: 'long',
            month: 'long',
            day: 'numeric'
        });
    }
}


function formatTime(timeStr) {
    const [hours, minutes] = timeStr.split(':');
    const hour = parseInt(hours, 10);
    const ampm = hour >= 12 ? 'PM' : 'AM';
    const hour12 = hour % 12 || 12;
    return `${hour12}:${minutes} ${ampm}`;
}


function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}


// ─────────────────────────────────────────────────────────────────────────────
// Config Loading
// ─────────────────────────────────────────────────────────────────────────────

async function loadConfig() {
    try {
        const resp = await fetch('/api/config');
        const config = await resp.json();

        if (config.phone_number) {
            const phoneDisplay = document.getElementById('phone-display');
            phoneDisplay.innerHTML = `Call us: <a href="tel:${config.phone_number}">${config.phone_number}</a>`;
            phoneDisplay.style.display = 'block';
        }
    } catch (error) {
        console.error('Failed to load config:', error);
    }
}


// ─────────────────────────────────────────────────────────────────────────────
// Initialization
// ─────────────────────────────────────────────────────────────────────────────

logEvent('system', 'Bobby\'s Table loaded');
logEvent('system', 'Ready to connect');

// Load config and reservations on page load
loadConfig();
refreshReservations();
