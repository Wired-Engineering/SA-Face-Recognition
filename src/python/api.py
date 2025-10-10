from fastapi import FastAPI, HTTPException, File, UploadFile, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sse_starlette.sse import EventSourceResponse
from pydantic import BaseModel
import uvicorn
import base64
import cv2
import json
import numpy as np
from PIL import Image, ImageOps
from io import BytesIO
import os
from typing import Optional, Dict
import pickle
import time
import logging
import asyncio
from contextlib import asynccontextmanager
import queue
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, unquote

# Load .env file for local development
from dotenv import load_dotenv
from pathlib import Path

# Find .env file in project root (two levels up from this file)
env_path = Path(__file__).parent.parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

# SocketIO imports
import socketio

from DatabaseManager import MySqlite3Manager
from utils import get_current_datetime_other_format
from SCRFD_Face_recognizer import SCRFDFaceRecognizer as FaceRecognizer
from config_manager import config_manager
from services.csv_processor import process_csv_with_progress_streaming

# Basic Authentication
security = HTTPBasic()

def verify_credentials(credentials: HTTPBasicCredentials = Depends(security)):
    """Verify basic auth credentials against database"""
    try:
        result = db.authenticate_admin(credentials.username, credentials.password)
        if result == 'Login Success':
            return credentials.username
        else:
            raise HTTPException(
                status_code=401,
                detail="Invalid authentication credentials"
            )
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication credentials"
        )

# Authentication dependency
def get_current_admin(admin_id: str = Depends(verify_credentials)):
    return admin_id

# Public endpoints that don't require authentication
PUBLIC_ENDPOINTS = {
    "/api/auth/login",
    "/api/system/health",
    "/api/display/settings",  # Welcome popup needs this
    "/api/docs",
    "/api/openapi.json",
    "/api/redoc"
}

# Public path patterns (for image serving - require auth to get list, but images themselves are public)
# This allows browser <img> tags to load images without auth headers
PUBLIC_IMAGE_PATTERNS = [
    "/api/display/background-image",  # Background image
    "/api/rtsp/stream-with-overlay",  # RTSP MJPEG stream
]

def is_image_endpoint(path: str) -> bool:
    """Check if path is a person image/photo endpoint"""
    import re
    # Match /api/people/{uuid}/image with optional query params
    # Match /api/people/{uuid}/photo/{filename} with optional query params
    return bool(
        re.match(r'^/api/people/[a-f0-9\-]+/image(\?.*)?$', path) or
        re.match(r'^/api/people/[a-f0-9\-]+/photo/[^/]+(\?.*)?$', path)
    )

# Lifespan manager for startup and shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("🚀 Face Recognition API starting...")
    print("📊 Database initialized")
    print("🤖 AI models loaded")
    print("📷 Camera system ready")
    print("✅ API ready at http://localhost:8000/api")
    print("📚 API docs available at http://localhost:8000/api/docs")

    # Ensure required directories exist
    os.makedirs("images", exist_ok=True)
    os.makedirs("system", exist_ok=True)

    # Load persistent detection state but clear session ownership on startup
    if get_independent_detection_active():
        print(f"🔄 Restored detection state: active (persistent from config)")
        # Clear session ownership so new clients can control detection
        global detection_session_owner, detection_session_start_time
        detection_session_owner = None
        detection_session_start_time = None
        print(f"🔄 Cleared session ownership - clients can now control detection")
    else:
        print(f"🔄 Detection state: inactive")

    yield

    # Shutdown - Cleanup SocketIO connections
    print("🔌 Cleaning up SocketIO connections...")
    detection_active.clear()
    print("✅ Cleanup complete")

# Create SocketIO server - Allow all origins
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins="*"  # Allow any origin including device IPs
)

app = FastAPI(
    title="Signature Aviation Face Recognition API",
    description="Face recognition system for person attendance",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json"
)

# CORS middleware for React frontend - Allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow any origin including device IPs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global authentication middleware
@app.middleware("http")
async def authenticate_requests(request: Request, call_next):
    """Global authentication middleware - protect all endpoints except public ones"""
    path = request.url.path

    # Skip authentication for OPTIONS requests (CORS preflight)
    if request.method == "OPTIONS":
        response = await call_next(request)
        return response

    # Skip authentication for public endpoints
    if path in PUBLIC_ENDPOINTS or path.startswith("/api/docs") or path.startswith("/static"):
        print(f"✅ Skipping auth for public endpoint: {path}")
        response = await call_next(request)
        return response

    # Skip authentication for image endpoints (browser <img> tags don't send auth headers)
    if is_image_endpoint(path) or any(path.startswith(pattern) for pattern in PUBLIC_IMAGE_PATTERNS):
        response = await call_next(request)
        return response

    # Check for basic auth header
    auth_header = request.headers.get("authorization")
    if not auth_header:
        # Note: In React dev mode (Strict Mode), effects run twice - this may cause duplicate requests
        print(f"⚠️  No auth header for {path} (PUBLIC_ENDPOINTS check: {path in PUBLIC_ENDPOINTS})")
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"}
        )

    if not auth_header.startswith("Basic "):
        print(f"❌ Auth failed for {path}: Invalid authorization header format: {auth_header[:20]}...")
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=401,
            content={"detail": "Authentication required"}
        )

    # Decode and verify credentials
    try:
        encoded_credentials = auth_header.split(" ")[1]
        decoded = base64.b64decode(encoded_credentials).decode("utf-8")
        username, password = decoded.split(":", 1)

        result = db.authenticate_admin(username, password)
        if result != 'Login Success':
            print(f"❌ Auth failed for {path}: Invalid credentials for user '{username}' (password length: {len(password)})")
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid authentication credentials"}
            )
    except Exception as e:
        print(f"❌ Auth failed for {path}: Exception during auth - {type(e).__name__}: {str(e)}")
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=401,
            content={"detail": "Invalid authentication credentials"}
        )

    # Continue to endpoint
    response = await call_next(request)
    return response

# Mount SocketIO app
socket_app = socketio.ASGIApp(sio, app)

# Initialize components
db = MySqlite3Manager()
# Initialize SCRFD face recognizer with default settings
face_recognizer = FaceRecognizer(
    thresold=0.5,  # Default threshold for SCRFD
    draw=True      # Enable drawing overlays
)

# Thread pool for parallel processing
thread_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rtsp_worker")

# SocketIO globals
detection_active: Dict[str, bool] = {}
welcome_screens: Dict[str, bool] = {}  # Track welcome screen connections
# Removed latest_recognition - welcome screens use WebSocket events, not polling
rtsp_streams: Dict[str, bool] = {}  # Track active RTSP streams
ffmpeg_streams: Dict[str, bool] = {}  # Track active ffmpeg streams with overlays
webcam_streams: Dict[str, bool] = {}  # Track active webcam streams

# Independent detection system - load state from config on startup
detection_session_id = None  # Track the current detection session
detection_session_owner = None  # Track who started the detection session
detection_session_start_time = None  # Track when detection started

def get_independent_detection_active():
    """Get detection state from persistent config"""
    return config_manager.is_detection_active()

def set_independent_detection_active(active: bool, owner_sid: str = None):
    """Set detection state and persist to config"""
    global detection_session_owner, detection_session_start_time

    if active and owner_sid:
        detection_session_owner = owner_sid
        detection_session_start_time = time.time()
        print(f"📝 Detection session started by: {owner_sid}")
    elif not active:
        detection_session_owner = None
        detection_session_start_time = None
        print(f"📝 Detection session cleared")

    return config_manager.set_detection_active(active)

def is_detection_session_expired():
    """Check if the current detection session has expired"""
    if not detection_session_start_time:
        return False

    # RTSP streams are backend-managed and should never timeout
    # since they're not tied to a specific user session
    camera_config = config_manager.get_camera_config()
    if camera_config.get('source') == 'rtsp':
        return False

    elapsed = time.time() - detection_session_start_time
    return elapsed > config_manager.get_detection_session_timeout()

def can_control_detection(sid: str):
    """Check if a client can control detection (start/stop)"""
    # Get camera configuration to determine source type
    camera_config = config_manager.get_camera_config()
    camera_source = camera_config.get('source', 'default')

    # For RTSP cameras, allow multiple viewers since backend handles everything
    if camera_source == 'rtsp':
        print(f"📡 RTSP camera detected - allowing multiple viewers for {sid}")
        return True

    # For webcam/browser cameras, enforce single session control
    # If no active session, anyone can start
    if not get_independent_detection_active():
        return True

    # If detection is active but no owner (e.g., restored from config), allow anyone to take control
    if detection_session_owner is None:
        print(f"🔄 Detection active with no owner - allowing {sid} to take control")
        return True

    # Check if session has expired
    if is_detection_session_expired():
        print(f"⏱️ Detection session expired (started {time.time() - detection_session_start_time:.0f}s ago)")
        return True

    # Check if this is the session owner
    if detection_session_owner == sid:
        return True

    # For now, also allow if the original owner has disconnected
    # This handles the case where someone leaves and comes back
    if detection_session_owner and detection_session_owner not in detection_active:
        print(f"👤 Original session owner {detection_session_owner} disconnected, allowing takeover by {sid}")
        return True

    return False

# Consolidated recognition and broadcasting functions
async def broadcast_recognition_to_welcome_screens(person_name: str, recognition_data: dict, source_type: str = ""):
    """Broadcast recognition data to all connected welcome screens"""
    if not welcome_screens:
        return

    source_prefix = f"{source_type}: " if source_type else ""
    print(f"🎯 {source_prefix}Broadcasting recognition to {len(welcome_screens)} welcome screens: {person_name}")

    # Create tasks for broadcasting to avoid blocking the detection loop
    tasks = []
    for welcome_screen_sid in list(welcome_screens.keys()):
        print(f"📺 {source_prefix}Sending recognition_result to welcome screen {welcome_screen_sid}")
        task = asyncio.create_task(
            sio.emit('recognition_result', recognition_data, to=welcome_screen_sid)
        )
        tasks.append(task)

    # Optional: Wait for all broadcasts to complete (but don't block on failures)
    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        print(f"⚠️ Some recognition broadcasts failed: {e}")

def create_recognition_data(best_match: dict, current_time: float) -> dict:
    """Create standardized recognition data structure"""
    return {
        'type': 'recognition',
        'user': {
            'person_id': best_match['person_id'],
            'person_name': best_match['person_name'],
            'name': best_match['person_name'],
            'userTitle': best_match.get('person_title'),
            'confidence': best_match['confidence'],
            'photo': None
        },
        'timestamp': current_time
    }

def should_broadcast_recognition(person_name: str, current_time: float, cooldown: float = 10.0) -> bool:
    """Check if enough time has passed to broadcast recognition (prevents spam)"""
    global last_detected_name, last_recognition_time

    time_since_last = current_time - last_recognition_time

    # Allow broadcasting if:
    # 1. This is the first detection ever (last_detected_name == "")
    # 2. It's a different person than last detected
    # 3. Same person but enough time has passed (cooldown expired)
    should_broadcast = (
        last_detected_name == "" or  # First detection
        person_name != last_detected_name or  # Different person
        time_since_last > cooldown  # Same person but cooldown expired
    )

    if should_broadcast:
        last_detected_name = person_name
        last_recognition_time = current_time
       # print(f"🎯 Broadcasting recognition for {person_name} (time since last: {time_since_last:.1f}s)")

        # Signal SSE clients of recognition change
        signal_recognition_change()
    #else:
        # print(f"🔄 Skipping recognition for {person_name} (cooldown: {time_since_last:.1f}s < {cooldown}s)")

    return should_broadcast

async def start_background_processing_for_camera_type():
    """Start appropriate background processing based on camera configuration"""
    camera_config = config_manager.get_camera_config()
    camera_source = camera_config.get('source')

    if camera_source == 'rtsp' and camera_config.get('rtsp_url'):
        if not any('welcome_screen_bg' in stream_id for stream_id in ffmpeg_streams.keys()):
            print(f"🎬 Starting background RTSP stream for recognition")
            asyncio.create_task(start_background_rtsp_for_welcome_screens())
        else:
            print(f"🎬 Background RTSP stream already running")
    elif camera_source in ['webcam', 'device', 'default']:
        print(f"📹 Using browser-based camera selection for {camera_source} source")
        print(f"📹 Recognition will be handled via frontend camera frames (process_frame_binary)")
        # No background stream needed - frontend will send frames via Socket.IO
    else:
        print(f"❌ Unsupported camera source for background recognition: {camera_source}")

async def run_with_auto_retry(process_func, stream_id: str, source_type: str, max_retries: int = 10, retry_delay: int = 5):
    """Generic auto-retry wrapper for background processing functions"""
    retry_count = 0

    while retry_count <= max_retries and get_independent_detection_active():
        try:
            print(f"🎬 Starting {source_type} background processing (attempt {retry_count + 1}/{max_retries + 1})")
            await process_func()
            break  # If successful, exit retry loop
        except Exception as e:
            retry_count += 1
            print(f"❌ Background {source_type} processing error (attempt {retry_count}/{max_retries + 1}): {e}")

            if retry_count <= max_retries and get_independent_detection_active():
                print(f"🔄 Retrying background {source_type} processing in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
            else:
                print(f"🛑 Background {source_type} processing failed permanently after {max_retries + 1} attempts")
                break

    # Clean up stream tracking based on source type
    stream_dict = ffmpeg_streams if source_type.lower() == 'rtsp' else webcam_streams
    if stream_id in stream_dict:
        del stream_dict[stream_id]
    print(f"🛑 Background {source_type} processing stopped")

# Recognition timing globals (inspired by original PyQt5 implementation)
last_detected_name = ""
last_recognition_time = 0.0
recognition_cooldown = 2.0  # Seconds - reduced to 2s to work with welcome screen's 3s timeout
# This ensures continuous display when someone remains in view (3s timeout > 2s cooldown)

# Multi-person recognition tracking for SSE
currently_recognized_people = {}  # Dict of {person_name: {'registration': str, 'last_seen': timestamp}}
recognition_expiry_time = 3.0  # Seconds - remove people after 3 seconds of not being detected

# SSE clients tracking for real-time recognition updates
sse_recognition_clients = set()
# Simple flag to signal SSE clients when recognition data changes
recognition_data_changed = False

def update_recognized_person(person_name: str, registration: str):
    """Add or update a currently recognized person"""
    global currently_recognized_people
    current_time = time.time()

    currently_recognized_people[person_name] = {
        'registration': registration,
        'last_seen': current_time
    }

    signal_recognition_change()

def cleanup_expired_recognitions():
    """Remove people who haven't been seen recently"""
    global currently_recognized_people
    current_time = time.time()
    expired_people = []

    for person_name, data in currently_recognized_people.items():
        time_since_last = current_time - data['last_seen']
        if time_since_last > recognition_expiry_time:
            expired_people.append(person_name)

    for person_name in expired_people:
        del currently_recognized_people[person_name]

    if expired_people:
        signal_recognition_change()

def signal_recognition_change():
    """Simple function to signal SSE clients that recognition data has changed"""
    global recognition_data_changed
    recognition_data_changed = True

def generate_thumbnail(person_id: str, size: int = 150) -> bool:
    """
    Generate thumbnail for a person's image.
    Supports both single-photo (person_id.png) and multi-photo (person_id%1.png) formats.
    Returns True if successful, False otherwise.
    """
    try:
        # Try standard format first
        image_path = f'images/{person_id}.png'

        # If not found, try multi-photo format (first photo)
        if not os.path.exists(image_path):
            image_path = f'images/{person_id}%1.png'
            if not os.path.exists(image_path):
                return False

        # Create thumbnails directory if it doesn't exist
        os.makedirs('images/thumbnails', exist_ok=True)

        thumbnail_path = f'images/thumbnails/{person_id}_{size}.jpg'

        # Generate thumbnail
        image = Image.open(image_path)
        image.thumbnail((size, size), Image.Resampling.LANCZOS)

        # Convert RGBA to RGB if needed (for JPEG)
        if image.mode == 'RGBA':
            background = Image.new('RGB', image.size, (255, 255, 255))
            background.paste(image, mask=image.split()[3] if len(image.split()) == 4 else None)
            image = background

        # Save as JPEG with good quality
        image.save(thumbnail_path, 'JPEG', quality=85, optimize=True)
        return True

    except Exception as e:
        print(f"Error generating thumbnail for {person_id}: {e}")
        return False

# Configure logging
logging.basicConfig(level=logging.INFO)

# SocketIO event handlers for WebRTC signaling
@sio.event
async def connect(sid, environ):
    print(f"🔌 Client connected: {sid}")

    # Check if independent detection is active when client connects
    if get_independent_detection_active():
        print(f"📋 Client connected while detection active (persistent state: True)")

        # Send detailed detection status to the new client
        elapsed = int(time.time() - detection_session_start_time) if detection_session_start_time else 0
        can_control = can_control_detection(sid)
        is_expired = is_detection_session_expired()

        # Get camera source to determine if multiple viewers are allowed
        camera_config = config_manager.get_camera_config()
        is_rtsp = camera_config.get('source') == 'rtsp'

        # For RTSP, always allow camera viewing; for webcam, only if they can control
        should_show_camera = is_rtsp or can_control

        await sio.emit('detection_status', {
            'active': True,
            'session_owner': detection_session_owner,
            'elapsed_seconds': elapsed,
            'can_control': can_control,
            'is_expired': is_expired,
            'should_show_camera': should_show_camera,
            'camera_source': camera_config.get('source', 'default'),
            'is_rtsp': is_rtsp,
            'message': 'RTSP stream - multiple viewers allowed' if is_rtsp and not can_control else ('Detection in progress by another user' if not can_control else 'Detection session active')
        }, to=sid)

@sio.event
async def disconnect(sid):
    global detection_session_id, detection_session_owner, detection_session_start_time

    print(f"🔌 Client disconnected: {sid}")

    # Check if the disconnecting client is the session owner
    was_owner = (detection_session_owner == sid)

    # Cleanup detection state for this client
    if sid in detection_active:
        del detection_active[sid]
    # Cleanup welcome screen state
    if sid in welcome_screens:
        del welcome_screens[sid]

    # If the disconnecting client was the session owner, clear ownership
    # This allows other clients to immediately take control
    if was_owner:
        print(f"👤 Session owner {sid} disconnected - clearing session ownership")
        detection_session_owner = None
        detection_session_start_time = None

        # Notify all remaining clients that detection is now available
        await sio.emit('detection_status', {
            'active': get_independent_detection_active(),
            'available': True,
            'session_owner': None,
            'message': 'Previous session owner disconnected - detection control is now available'
        })
    else:
        # Detection state is controlled by persistent config and explicit admin actions only
        # Client disconnections should NOT automatically stop detection
        print(f"🔄 Client disconnected - detection state remains unchanged (controlled by admin only)")

@sio.event
async def start_detection(sid, data):
    """Start face detection for a client"""
    global detection_session_id

    # Track if this is a takeover (for logging/notification purposes)
    is_takeover = False
    takeover_reason = ""

    # Check if there's an existing owner that will be replaced
    if detection_session_owner and detection_session_owner != sid:
        if is_detection_session_expired():
            is_takeover = True
            takeover_reason = "session expired"
        elif detection_session_owner not in detection_active:
            is_takeover = True
            takeover_reason = "previous owner disconnected"

    # Check if this client can control detection
    if not can_control_detection(sid):
        elapsed = time.time() - detection_session_start_time if detection_session_start_time else 0
        print(f"⚠️ Detection already in progress by {detection_session_owner} ({elapsed:.0f}s ago) - rejecting request from client {sid}")
        await sio.emit('detection_error', {
            'status': 'error',
            'message': 'Detection is already in progress by another user. Please wait until the current session is finished.',
            'session_owner': detection_session_owner,
            'elapsed_time': int(elapsed)
        }, to=sid)
        return

    if is_takeover:
        print(f"🔄 Session takeover by {sid} - reason: {takeover_reason}")

    print(f"🔍 Starting face detection for client {sid}")
    detection_active[sid] = True

    # Start independent detection with owner tracking
    set_independent_detection_active(True, owner_sid=sid)
    detection_session_id = f"session_{int(time.time())}"
    print(f"🎯 Starting independent detection session: {detection_session_id}")

    # Notify face recognizer that detection is starting
    face_recognizer.start_detection()

    # Reset recognition cooldown when starting new detection session
    global last_detected_name, last_recognition_time
    last_detected_name = ""
    last_recognition_time = 0.0
    print(f"🔄 Reset recognition cooldown for new detection session")

    # Start background stream processing for recognition if camera is configured
    camera_config = config_manager.get_camera_config()
    print(f"🔍 Camera config: source={camera_config.get('source')}, rtsp_url={camera_config.get('rtsp_url')}")

    await start_background_processing_for_camera_type()

    # Notify the requesting client that detection started
    await sio.emit('detection_started', {'status': 'started'}, to=sid)

    # Get camera configuration to determine broadcast behavior
    camera_config = config_manager.get_camera_config()
    is_rtsp = camera_config.get('source') == 'rtsp'

    # For RTSP, allow multiple viewers; for webcam, restrict to one
    if is_rtsp:
        # RTSP allows multiple viewers - broadcast that stream is available to all
        await sio.emit('detection_status_changed', {
            'active': True,
            'available': True,  # RTSP remains available for others
            'session_owner': sid,
            'should_show_camera': True,  # RTSP allows multiple camera viewers
            'camera_source': 'rtsp',
            'is_rtsp': True,
            'message': 'RTSP detection active - multiple viewers supported'
        }, skip_sid=sid)
    else:
        # Webcam restricts to single user - broadcast unavailable to others
        await sio.emit('detection_status_changed', {
            'active': True,
            'available': False,
            'session_owner': sid,
            'should_show_camera': False,  # Other clients should not show camera
            'camera_source': camera_config.get('source', 'default'),
            'is_rtsp': False,
            'message': 'Detection session started by another user'
        }, skip_sid=sid)

    # Also send immediate status to all currently connected clients
    try:
        # Get all connected clients in the default namespace
        connected_clients = list(sio.manager.get_participants('/', '/'))
        for client_sid in connected_clients:
            if client_sid != sid:  # Skip the session owner
                await sio.emit('detection_status', {
                    'active': True,
                    'session_owner': sid,
                    'can_control': is_rtsp,  # For RTSP, all can control; for webcam, only owner
                    'should_show_camera': is_rtsp,  # For RTSP, all can view; for webcam, only owner
                    'camera_source': camera_config.get('source', 'default'),
                    'is_rtsp': is_rtsp,
                    'message': 'RTSP stream available for viewing' if is_rtsp else 'Detection in progress by another user'
                }, to=client_sid)
    except Exception as e:
        print(f"⚠️ Error notifying connected clients: {e}")


@sio.event
async def start_video_stream(sid, data):
    """Start video streaming with overlays for a client"""
    print(f"🎥 Starting video stream for client {sid}")
    detection_active[sid] = True
    await sio.emit('stream_started', {'status': 'started'}, to=sid)

@sio.event
async def stop_detection(sid, data):
    """Stop face detection for a client"""
    global detection_session_id

    # Check if this is an explicit admin stop request
    is_admin_stop = data and data.get('admin_stop', False)

    # Only allow stopping if this client can control detection
    if is_admin_stop and not can_control_detection(sid):
        print(f"⚠️ Client {sid} not authorized to stop detection started by {detection_session_owner}")
        await sio.emit('detection_error', {
            'status': 'error',
            'message': 'You cannot stop a detection session started by another user.',
            'session_owner': detection_session_owner
        }, to=sid)
        return

    print(f"🛑 Stopping face detection for client {sid} (admin_stop: {is_admin_stop})")
    was_admin_client = sid in detection_active
    if was_admin_client:
        del detection_active[sid]

    # Only stop independent detection if explicitly requested by admin
    # OR if no welcome screens AND no admin clients are connected AND not a page refresh
    if is_admin_stop:
        set_independent_detection_active(False, owner_sid=None)
        detection_session_id = None
        print(f"🛑 Admin explicitly stopped detection - setting detection.active = false")

        # Notify face recognizer that detection is stopping (processes queued operations)
        face_recognizer.stop_detection()

        # Stop ALL streams when admin explicitly stops detection (not just background)
        rtsp_stream_count = len(rtsp_streams)
        ffmpeg_stream_count = len(ffmpeg_streams)
        webcam_stream_count = len(webcam_streams)

        rtsp_streams.clear()
        ffmpeg_streams.clear()
        webcam_streams.clear()

        total_stopped = rtsp_stream_count + ffmpeg_stream_count + webcam_stream_count
        print(f"🛑 Admin stop: Cleared {rtsp_stream_count} RTSP, {ffmpeg_stream_count} FFmpeg, {webcam_stream_count} webcam streams (total: {total_stopped})")

        # Broadcast to all clients that detection is now stopped and available
        await sio.emit('detection_status_changed', {
            'active': False,
            'available': True,
            'message': 'Detection session stopped - detection is now available',
            'previous_owner': detection_session_owner
        })

    elif len(welcome_screens) == 0 and len(detection_active) == 0:
        # Detection remains active in config - welcome screens can still connect and receive events
        print(f"🔄 No connected clients, but keeping detection active (persistent state: {get_independent_detection_active()}) for potential welcome screens")
        # Reset cooldown to ensure welcome screens get immediate updates when they reconnect
        global last_detected_name, last_recognition_time
        last_detected_name = ""
        last_recognition_time = 0.0
        print(f"🔄 Reset recognition cooldown for continuous welcome screen updates")
    else:
        print(f"🔄 Keeping independent detection active (persistent state: {get_independent_detection_active()}) - {len(welcome_screens)} welcome screens, {len(detection_active)} admin clients")
        # Also reset cooldown when admin disconnects but welcome screens remain
        if not is_admin_stop and was_admin_client:
            # Use the already declared global variables
            last_detected_name = ""
            last_recognition_time = 0.0
            print(f"🔄 Admin disconnected - reset cooldown for continuous welcome screen updates")

    await sio.emit('detection_stopped', {'status': 'stopped'}, to=sid)

@sio.event
async def register_welcome_screen(sid, data):
    """Register a welcome screen popup"""
    print(f"📺 Welcome screen registered: {sid}")
    welcome_screens[sid] = True

    # Check if detection should be maintained/started for welcome screens
    detection_state = get_independent_detection_active()
    admin_clients = len(detection_active)

    if detection_state:
        print(f"📋 Welcome screen registered - detection already active (persistent state: True, admin clients: {admin_clients})")

        # Check if background processing should be restarted (in case it stopped due to errors)
        print(f"🔄 Welcome screen connected - checking if background processing needs restart...")
        await start_background_processing_for_camera_type()
    else:
        print(f"📋 Welcome screen registered - detection inactive (persistent state: False, admin clients: {admin_clients})")
        print(f"📋 Welcome screen will receive recognition events once an admin starts detection")

    # Send current display settings to the newly connected welcome screen
    try:
        display_config = config_manager.get_display_config()
        current_settings = {
            'timer': display_config.get('timer', 5),
            'background_color': display_config.get('background_color', '#FFE8D4'),
            'font_color': display_config.get('font_color', '#032F5C'),
            'cloud_color': display_config.get('cloud_color', '#4ECDC4'),
            'use_background_image': display_config.get('use_background_image', False),
            'font_family': display_config.get('font_family', 'Inter'),
            'font_size': display_config.get('font_size', 'medium'),
            'bubble_size': display_config.get('bubble_size', 'medium')
        }

        print(f"📋 Sending current display settings to welcome screen {sid}")
        await sio.emit('display_settings_updated', current_settings, to=sid)
    except Exception as e:
        print(f"❌ Error sending display settings to welcome screen {sid}: {e}")

    await sio.emit('welcome_screen_registered', {'status': 'registered'}, to=sid)

@sio.event
async def unregister_welcome_screen(sid, data):
    """Unregister a welcome screen popup"""
    print(f"📺 Welcome screen unregistered: {sid}")
    if sid in welcome_screens:
        del welcome_screens[sid]

    # Welcome screen disconnection should NOT auto-stop detection
    # Detection should only be stopped explicitly by admin users
    print(f"📋 Welcome screen disconnected - detection state unchanged (admin controlled)")

    await sio.emit('welcome_screen_unregistered', {'status': 'unregistered'}, to=sid)

@sio.event
async def request_background_image(sid, data):
    """Send background image data to welcome screen"""
    print(f"🖼️ Background image requested by welcome screen: {sid}")
    try:
        display_config = config_manager.get_display_config()
        background_image_path = display_config.get('background_image')
        use_background_image = display_config.get('use_background_image', False)

        if background_image_path and use_background_image and os.path.exists(background_image_path):
            # Read file and convert to base64
            with open(background_image_path, 'rb') as f:
                contents = f.read()

            # Determine MIME type from file extension
            file_extension = background_image_path.split('.')[-1].lower()
            mime_type_map = {
                'png': 'image/png',
                'jpg': 'image/jpeg',
                'jpeg': 'image/jpeg',
                'webp': 'image/webp'
            }
            mime_type = mime_type_map.get(file_extension, 'image/jpeg')

            image_base64 = base64.b64encode(contents).decode('utf-8')
            image_data_url = f"data:{mime_type};base64,{image_base64}"

            await sio.emit('background_image_data', {
                'backgroundImage': image_data_url,
                'useBackgroundImage': True
            }, to=sid)
            print(f"✅ Sent background image data to {sid}")
        else:
            print(f"ℹ️ No background image available for {sid}")
    except Exception as e:
        print(f"❌ Error sending background image to {sid}: {e}")

@sio.event
async def process_frame_binary(sid, data):
    """
    Process video frame from browser webcam via binary data - more efficient than base64
    Browser captures webcam → sends binary frames → backend processes → returns processed frame
    """
   #print(f"📹 Binary frame processing for client {sid}")

    try:
        # Check if detection is active for this client
        if not detection_active.get(sid, False):
            return

        # Get binary frame data
        frame_bytes = data['frame']

        # Convert binary data to numpy array
        nparr = np.frombuffer(frame_bytes, np.uint8)
        cv_frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if cv_frame is None:
            print(f"❌ Failed to decode frame for {sid}")
            return

        # Run face detection
        frame_features, faces = face_recognizer.recognize_face(cv_frame)

        # Process detection results using unified pipeline
        detection_results, recognition_results = process_faces_unified(faces, frame_features)

        # Broadcast recognition results to welcome screens
        for recognition_data in recognition_results:
            for welcome_screen_sid in welcome_screens.keys():
                await sio.emit('recognition_result', recognition_data, to=welcome_screen_sid)

        # Draw overlays on frame for browser webcam
        if detection_results:
            cv_frame = draw_detection_overlays_on_frame(cv_frame, detection_results)

        # Send just the detection results, let frontend handle video display
        # No need to send processed frames back - frontend can overlay detection results
        await sio.emit('frame_processed_binary', {
            "faces": detection_results,
            "timestamp": time.time(),
            "frame_size": {"width": cv_frame.shape[1], "height": cv_frame.shape[0]}
            # No processed_frame - frontend will overlay detection results on live video
        }, to=sid)

        #if len(detection_results) > 0:
            #print(f"🔍 Sent {len(detection_results)} detection results with binary frame to {sid}")

    except Exception as e:
        print(f"❌ Error processing binary frame for {sid}: {e}")
        await sio.emit('detection_error', {"error": str(e)}, to=sid)



def process_faces_unified(faces, frame_features, scale_x=1.0, scale_y=1.0, frame_count=0):
    """
    Unified face processing pipeline for both webcam and RTSP
    Eliminates code duplication and optimizes database queries

    Args:
        faces: List of FaceDetection objects
        frame_features: List of face feature vectors
        scale_x, scale_y: Scaling factors for bbox coordinates
        frame_count: Optional frame number

    Returns:
        Tuple of (detection_results, recognition_results) lists
    """
    if faces is None or len(faces) == 0:
        return [], []

    detection_results = []
    recognition_results = []

    # Batch collect person IDs for single DB query
    person_ids_to_query = set()

    # First pass: collect all person IDs that need DB lookup
    for i, face_detection in enumerate(faces):
        if i < len(frame_features) and face_recognizer.dictionary:
            feature = frame_features[i]

            # Use ensemble matching
            try:
                landmarks = face_detection.landmarks if hasattr(face_detection, 'landmarks') else None
                match_result, (person_id, score) = face_recognizer.ensemble_match(feature, landmarks)

                if match_result:
                    base_person_id = person_id.split('%')[0] if '%' in person_id else person_id
                    person_ids_to_query.add(base_person_id)
            except Exception:
                # Fallback to standard matching
                for person_id, ref_feature in face_recognizer.dictionary.items():
                    score = face_recognizer.face_recognizer.match(feature, ref_feature)
                    if score > face_recognizer.threshold:
                        person_ids_to_query.add(person_id)
                        break

    # Batch query database for all needed person info
    person_data_cache = {}
    if person_ids_to_query:
        # Single query to get all person names, titles, and registrations
        for person_id in person_ids_to_query:
            try:
                person_data_cache[person_id] = {
                    'name': db.get_person_name(person_id),
                    'title': db.get_person_title(person_id),
                    'registration': db.get_registration_id(person_id)
                }
            except Exception:
                person_data_cache[person_id] = {'name': 'Unknown', 'title': '', 'registration': 'N/A'}

    # Second pass: build results using cached data
    for i, face_detection in enumerate(faces):
        x1, y1, w, h = face_detection.bbox
        x2, y2 = x1 + w, y1 + h

        # Apply scaling
        x1_scaled = int(x1 * scale_x)
        y1_scaled = int(y1 * scale_y)
        x2_scaled = int(x2 * scale_x)
        y2_scaled = int(y2 * scale_y)

        result = {
            'bbox': [x1_scaled, y1_scaled, x2_scaled, y2_scaled],
            'confidence': float(face_detection.confidence),
            'quality_score': float(face_detection.quality_score),
            'face_area': int(face_detection.face_area),
            'is_frontal': bool(face_detection.is_frontal),
            'recognized': False,
            'person_name': 'Unknown',
            'match_confidence': 0.0,
            'frame_count': frame_count
        }

        # Add landmarks if available
        if face_recognizer.include_landmarks and face_detection.landmarks is not None:
            result['landmarks'] = face_detection.landmarks.tolist()
            result['landmark_count'] = len(face_detection.landmarks)

        # Face recognition matching using cached data
        if i < len(frame_features) and face_recognizer.dictionary:
            feature = frame_features[i]
            best_match = None

            try:
                landmarks = face_detection.landmarks if hasattr(face_detection, 'landmarks') else None
                match_result, (person_id, score) = face_recognizer.ensemble_match(feature, landmarks)

                if match_result:
                    base_person_id = person_id.split('%')[0] if '%' in person_id else person_id
                    if base_person_id in person_data_cache:
                        best_match = {
                            'person_id': base_person_id,
                            'person_name': person_data_cache[base_person_id]['name'],
                            'person_title': person_data_cache[base_person_id]['title'],
                            'confidence': float(score)
                        }

            except Exception as e:
                print(f"❌ Ensemble matching error, using fallback: {e}")
                # Fallback matching with cached data
                highest_score = 0
                for person_id, ref_feature in face_recognizer.dictionary.items():
                    score = face_recognizer.face_recognizer.match(feature, ref_feature)
                    if score > face_recognizer.threshold and score > highest_score:
                        highest_score = score
                        if person_id in person_data_cache:
                            best_match = {
                                'person_id': person_id,
                                'person_name': person_data_cache[person_id]['name'],
                                'person_title': person_data_cache[person_id]['title'],
                                'confidence': float(score)
                            }

            # Apply match results
            if best_match:
                result.update({
                    'person_id': best_match['person_id'],
                    'person_name': best_match['person_name'],
                    'person_title': best_match['person_title'],
                    'match_confidence': best_match['confidence'],
                    'recognized': True
                })

                # Build recognition data for welcome screen broadcasting
                recognition_data = {
                    'type': 'recognition',
                    'user': {
                        'person_id': best_match['person_id'],
                        'person_name': best_match['person_name'],
                        'name': best_match['person_name'],
                        'userTitle': best_match['person_title'],
                        'confidence': best_match['confidence'],
                        'photo': None
                    },
                    'timestamp': time.time()
                }
                recognition_results.append(recognition_data)

                # Update multi-person SSE tracking - get registration from our person_data lookup
                person_registration = person_data_cache.get(best_match['person_id'], {}).get('registration', 'N/A')
                update_recognized_person(best_match['person_name'], person_registration)

                # Also trigger original welcome screen broadcast for compatibility
                should_broadcast_recognition(best_match['person_name'], time.time(), recognition_cooldown)

        detection_results.append(result)

    return detection_results, recognition_results

def draw_detection_overlays_on_frame(frame, faces):
    """Draw detection overlays directly on video frame"""
    overlay_frame = frame.copy()

    for face in faces:
        x1, y1, x2, y2 = face['bbox']

        # Draw bounding box
        color = (0, 255, 0) if face.get('recognized', False) else (0, 0, 255)  # Green for recognized, red for unknown
        cv2.rectangle(overlay_frame, (x1, y1), (x2, y2), color, 2)

        # Draw label
        if face.get('recognized', False):
            label = f"{face['person_name']} ({int(face['match_confidence'] * 100)}%)"
            label_color = (255, 255, 255)
            bg_color = (0, 255, 0)
        else:
            label = "Unknown"
            label_color = (255, 255, 255)
            bg_color = (0, 0, 255)

        # Get text size
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.7
        thickness = 2
        (text_width, text_height), _ = cv2.getTextSize(label, font, font_scale, thickness)

        # Draw text (without background rectangle)
        cv2.putText(overlay_frame, label, (x1, y1 - 5), font, font_scale, label_color, thickness)

    return overlay_frame


def configure_hardware_acceleration():
    """Configure OpenCV backend based on entrypoint GPU detection"""
    import os

    # Check if GPU acceleration was detected by entrypoint script
    enable_gpu = os.getenv('ENABLE_GPU_ACCELERATION', '').lower() in ('true', '1', 'yes')

    if not enable_gpu:
        print("💻 Using CPU-only processing (default for production stability)")
        print("💡 To enable GPU acceleration: set ENABLE_GPU_ACCELERATION=true")
        cv2.ocl.setUseOpenCL(False)
        return "cpu"

    # Use GPU backend type detected by entrypoint (nvidia, vaapi, etc.)
    backend_type = os.getenv('GPU_BACKEND_TYPE', 'cpu').lower()

    # Enable OpenCL for OpenCV operations (works with NVIDIA/Intel/AMD)
    if cv2.ocl.haveOpenCL():
        cv2.ocl.setUseOpenCL(True)
        print(f"✅ OpenCL enabled for OpenCV operations (device: {cv2.ocl.Device.getDefault().name()})")
    else:
        print("ℹ️ OpenCL not available - OpenCV will use CPU")

    if backend_type == 'nvidia':
        print("🚀 Using NVIDIA GPU backend (detected by entrypoint)")
        print("ℹ️ ONNX models: CUDAExecutionProvider")
        print("ℹ️ OpenCV preprocessing: OpenCL (if available)")
        return "nvidia"
    elif backend_type == 'vaapi':
        print("🚀 Using VAAPI backend for Intel/AMD GPU (detected by entrypoint)")
        return "vaapi"
    elif backend_type == 'intel_mfx':
        print("🚀 Using Intel QuickSync Video (MFX) backend (detected by entrypoint)")
        return "intel_mfx"
    else:
        print(f"⚠️ Unknown GPU backend type: {backend_type}, falling back to CPU")
        cv2.ocl.setUseOpenCL(False)
        return "cpu"


def create_optimized_capture(rtsp_url, hw_backend="cpu"):
    """Create an optimized VideoCapture with hardware acceleration and ultra-low latency for RTSP"""
    cap = None

    print(f"🔧 Opening RTSP stream with low-latency settings: {rtsp_url}")

    if hw_backend in ("cuda", "nvidia"):
        # Try CUDA-accelerated capture with low-latency GStreamer pipeline
        try:
            # GStreamer pipeline optimized for ultra-low latency
            gst_pipeline = (
                f'rtspsrc location={rtsp_url} protocols=tcp latency=0 ! '
                'rtph264depay ! h264parse ! nvh264dec ! '
                'videoconvert ! appsink max-buffers=1 drop=true'
            )
            cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)
            if cap.isOpened():
                print("✅ CUDA GStreamer pipeline initialized with low latency")
        except Exception as e:
            print(f"⚠️ CUDA GStreamer failed: {e}")
            pass

    elif hw_backend == "intel_mfx":
        # Try Intel Quick Sync Video (QSV) with Media SDK
        try:
            print(f"🔧 Initializing Intel QuickSync capture with low latency")
            cap = cv2.VideoCapture(rtsp_url, cv2.CAP_INTEL_MFX)
            if cap.isOpened():
                print("✅ Intel QuickSync Video capture initialized successfully")
            else:
                print("⚠️ Intel QuickSync capture failed to open, falling back to FFmpeg")
                cap = None
        except Exception as e:
            print(f"❌ Intel QuickSync initialization failed: {e}")
            cap = None

    elif hw_backend == "vaapi":
        # Try VAAPI hardware acceleration with low-latency GStreamer pipeline
        try:
            gst_pipeline = (
                f'rtspsrc location={rtsp_url} protocols=tcp latency=0 ! '
                'rtph264depay ! h264parse ! vaapih264dec ! '
                'videoconvert ! appsink max-buffers=1 drop=true'
            )
            cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)
            if cap.isOpened():
                print("✅ VAAPI GStreamer pipeline initialized with low latency")
        except Exception as e:
            print(f"⚠️ VAAPI GStreamer failed: {e}, falling back to FFmpeg")
            # Fallback to regular FFMPEG with low-latency settings
            cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)

    elif hw_backend == "dshow":
        # Try DirectShow with hardware acceleration
        try:
            cap = cv2.VideoCapture(rtsp_url, cv2.CAP_DSHOW)
        except:
            pass

    # Fallback to FFmpeg with aggressive low-latency settings
    if cap is None or not cap.isOpened():
        print("🔧 Using FFmpeg backend with ultra-low latency settings")

        # Set FFmpeg environment variables for minimal latency
        os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = (
            'rtsp_transport;tcp|'
            'fflags;nobuffer|'
            'flags;low_delay|'
            'analyzeduration;1000000|'  # 1 second max analysis
            'probesize;1000000|'  # 1MB probe size
            'max_delay;0|'
            'reorder_queue_size;0'
        )

        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)

    # Apply ultra-aggressive low-latency capture settings
    if cap.isOpened():
        # Critical: Minimize buffer to absolute minimum (1 frame)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        # Set target FPS
        cap.set(cv2.CAP_PROP_FPS, 30)

        # Disable frame interpolation and buffering
        try:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('H', '2', '6', '4'))
        except:
            pass

        # Additional latency reduction settings
        try:
            # Set minimal timeout for frame acquisition (100ms)
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 100)
        except:
            pass

        print("✅ Low-latency capture settings applied (buffer=1, tcp transport, no buffering)")
    else:
        print(f"❌ Failed to open RTSP stream with all backends")

    return cap


def flush_rtsp_buffer(cap, num_frames=5):
    """
    Flush the RTSP buffer by grabbing multiple frames and only retrieving the latest.
    This ensures we're always processing the most recent frame, not buffered old frames.

    Args:
        cap: OpenCV VideoCapture object
        num_frames: Number of frames to grab (flush) before retrieving

    Returns:
        (ret, frame): Latest frame from the stream
    """
    # Grab multiple frames without decoding to flush the buffer
    for _ in range(num_frames):
        if not cap.grab():
            break

    # Retrieve only the last grabbed frame
    return cap.retrieve()


def process_frame_threaded(frame_data):
    """Process a frame in a separate thread for face detection"""
    frame, frame_count = frame_data

    try:
        # Resize frame to consistent size like original implementation (800x600)
        display_frame = cv2.resize(frame, (800, 600))
        frame_features, faces = face_recognizer.recognize_face(display_frame)

        # Calculate scaling factors from display frame back to original frame
        original_height, original_width = frame.shape[:2]
        scale_x = original_width / 800.0
        scale_y = original_height / 600.0

        # Process detection results using unified pipeline
        detection_results, recognition_results = process_faces_unified(
            faces, frame_features, scale_x, scale_y, frame_count
        )

        return detection_results, frame_count

    except Exception as e:
        print(f"❌ Error in threaded frame processing: {e}")
        return [], frame_count


async def process_rtsp_with_ffmpeg_overlay(rtsp_url, output_queue, stop_event):
    """Process RTSP stream with multithreading, hardware acceleration, and overlay detection results"""
    print(f"🎬 Starting optimized RTSP processing with multithreading: {rtsp_url}")

    # Configure hardware acceleration
    hw_backend = configure_hardware_acceleration()

    try:
        # Initialize hardware-accelerated capture
        loop = asyncio.get_event_loop()
        cap = await loop.run_in_executor(None, create_optimized_capture, rtsp_url, hw_backend)

        if not cap.isOpened():
            print(f"❌ Failed to open RTSP stream: {rtsp_url}")
            return

        # Get video properties
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        print(f"📺 Video properties: {width}x{height} @ {fps}fps with {hw_backend} backend")
        print(f"🚀 Using frame buffer flushing to maintain low latency (always processing latest frame)")

        frame_count = 0
        detection_results_cache = []
        pending_futures = {}  # Track pending detection tasks
        consecutive_failures = 0
        max_consecutive_failures = 100  # Exit after 100 consecutive frame read failures

        # Keep detection running as long as it's marked active
        while not stop_event.is_set() and get_independent_detection_active():
            # Flush buffer and read latest frame to avoid lag buildup
            # Use grab()/retrieve() pattern to always get the freshest frame
            # This grabs 3 frames and only retrieves the last one, discarding buffered frames
            ret, frame = await loop.run_in_executor(None, flush_rtsp_buffer, cap, 3)

            if not ret or frame is None:
                consecutive_failures += 1
                print(f"⚠️ Failed to read frame from RTSP stream (attempt {consecutive_failures}/{max_consecutive_failures})")

                if consecutive_failures >= max_consecutive_failures:
                    print(f"❌ Too many consecutive failures ({consecutive_failures}), stopping RTSP stream")
                    break

                await asyncio.sleep(0.1)  # Wait longer between retries
                continue

            # Reset failure counter on successful read
            consecutive_failures = 0
            frame_count += 1

            # Process every 2nd frame for better performance while maintaining responsiveness
            if frame_count % 2 == 0:
                # Submit frame processing to thread pool
                future = loop.run_in_executor(
                    thread_pool,
                    process_frame_threaded,
                    (frame.copy(), frame_count)
                )
                pending_futures[frame_count] = future

                # Limit number of pending futures to prevent memory issues
                if len(pending_futures) > 6:  # Allow max 6 frames processing in parallel
                    # Wait for oldest future to complete
                    oldest_frame = min(pending_futures.keys())
                    try:
                        await pending_futures[oldest_frame]
                    except Exception as e:
                        print(f"❌ Error waiting for frame processing: {e}")
                    del pending_futures[oldest_frame]

            # Check for completed detection results
            completed_futures = []
            for fc, future in pending_futures.items():
                if future.done():
                    try:
                        detection_results, _ = await future
                        detection_results_cache = detection_results
                        completed_futures.append(fc)

                        # Handle recognition results
                        for result in detection_results:
                            if result['recognized']:
                                # Recognition cooldown and broadcasting logic
                                current_time = time.time()
                                person_name = result['person_name']

                                # Only broadcast if enough time has passed since last recognition
                                if should_broadcast_recognition(person_name, current_time, recognition_cooldown):
                                    # Create standardized recognition data
                                    best_match = {
                                        'person_id': result.get('person_id'),
                                        'person_name': person_name,
                                        'person_title': db.get_person_title(result.get('person_id', '')),
                                        'confidence': result['match_confidence']
                                    }
                                    recognition_data = create_recognition_data(best_match, current_time)


                                    # Broadcast to welcome screens via SocketIO
                                    await broadcast_recognition_to_welcome_screens(person_name, recognition_data, "RTSP")

                    except Exception as e:
                        print(f"❌ Error processing detection results: {e}")
                        completed_futures.append(fc)

            # Remove completed futures
            for fc in completed_futures:
                if fc in pending_futures:
                    del pending_futures[fc]

            # Reset recognition state when no faces detected
            if not detection_results_cache:
                global last_detected_name, last_recognition_time
                if last_detected_name != "":
                    print(f"🔄 No faces detected - resetting recognition state (was: {last_detected_name})")
                    last_detected_name = ""
                    last_recognition_time = 0.0
                    # Signal SSE clients of recognition change
                    signal_recognition_change()

            # Send detection results to frontend for UI updates
            if detection_results_cache and get_independent_detection_active():
                for sid in detection_active.keys():
                    asyncio.create_task(sio.emit('face_detection_result', {
                        "faces": detection_results_cache,
                        "timestamp": time.time(),
                        "frame_size": {"width": frame.shape[1], "height": frame.shape[0]}
                    }, to=sid))

            # Draw overlays on frame using cached detection results
            if detection_results_cache:
                frame = draw_detection_overlays_on_frame(frame, detection_results_cache)

            # Hardware-accelerated encoding if available
            encode_params = [cv2.IMWRITE_JPEG_QUALITY, 90]  # Higher quality for better stream
            if hw_backend in ["cuda", "intel_mfx", "vaapi"]:
                encode_params.extend([cv2.IMWRITE_JPEG_OPTIMIZE, 1])

            _, buffer = cv2.imencode('.jpg', frame, encode_params)

            # Dynamic frame rate limiting based on processing load
            processing_load = len(pending_futures) / 6.0  # Normalize to 0-1
            sleep_time = 0.015 + (processing_load * 0.02)  # 15-35ms depending on load
            await asyncio.sleep(sleep_time)

            # Put frame in output queue (non-blocking)
            if not output_queue.full():
                try:
                    output_queue.put_nowait(buffer.tobytes())
                except queue.Full:
                    pass  # Skip frame if queue is full

        # Wait for any remaining futures to complete
        if pending_futures:
            print("🔄 Waiting for remaining detection tasks to complete...")
            for future in pending_futures.values():
                try:
                    await asyncio.wait_for(future, timeout=2.0)
                except asyncio.TimeoutError:
                    print("⚠️ Detection task timeout during cleanup")
                except Exception:
                    pass  # Ignore errors during cleanup

        cap.release()
        print("🛑 Optimized RTSP processing stopped")

    except Exception as e:
        print(f"❌ Error in optimized RTSP processing: {e}")




# Simple camera testing without enumeration
def test_single_camera(index):
    """Test a single camera index"""
    try:
        cap = cv2.VideoCapture(index)
        if cap.isOpened():
            ret, frame = cap.read()
            cap.release()
            return ret and frame is not None
        cap.release()
        return False
    except:
        return False

# Load RTSP settings
def load_rtsp_settings():
    try:
        with open('system/rtspin.pkl', 'rb') as f:
            settings = pickle.load(f)
            return settings.get('rtsp_url', '')
    except:
        return ''

def save_rtsp_settings(rtsp_url):
    try:
        settings = {'rtsp_url': rtsp_url}
        os.makedirs('system', exist_ok=True)
        with open('system/rtspin.pkl', 'wb') as f:
            pickle.dump(settings, f)
        return True
    except:
        return False

# Pydantic models
class LoginRequest(BaseModel):
    admin_id: str
    password: str

class personRegistration(BaseModel):
    person_name: str
    person_title: str
    person_registration: str
    image_data: str

class AdditionalPhotoUpload(BaseModel):
    image_data: str
    description: Optional[str] = None  # Optional user description like "with glasses"

class AdminPasswordChange(BaseModel):
    old_id: str
    old_password: str
    new_id: str
    new_password: str
    confirm_password: str

class CameraSettings(BaseModel):
    source: Optional[str] = "default"  # default, webcam, device, and rtsp supported
    device_id: Optional[str] = None  # For webcam/device: device index (0, 1, 2...) or device ID string
    rtsp_url: Optional[str] = None

class DisplaySettings(BaseModel):
    timer: Optional[int] = 5
    background_color: Optional[str] = "#FFE8D4"
    font_color: Optional[str] = "#032F5C"
    cloud_color: Optional[str] = "#4ECDC4"
    use_background_image: Optional[bool] = False
    background_image: Optional[str] = None
    font_family: Optional[str] = "Inter"
    font_size: Optional[str] = "medium"
    bubble_size: Optional[str] = "medium"

class DetectionSettings(BaseModel):
    detection_confidence: Optional[float] = 0.5
    tracking_confidence: Optional[float] = 0.7  # Higher default for video tracking
    max_faces: Optional[int] = 20
    refine_landmarks: Optional[bool] = True
    unlimited_faces: Optional[bool] = False
    include_landmarks: Optional[bool] = False

class RecognitionSettings(BaseModel):
    recognition_threshold: Optional[float] = 0.5  # Face recognition confidence threshold
    face_quality_threshold: Optional[float] = 0.3  # Minimum face quality for recognition

class FaceDetectionRequest(BaseModel):
    image_data: str


# Authentication endpoints
@app.post("/api/auth/login")
async def login(request: LoginRequest):
    """Authenticate admin user"""
    try:
        result = db.authenticate_admin(request.admin_id, request.password)
        if result == 'Login Success':
            admin_name = db.get_admin_name(request.admin_id)
            return {
                'success': True,
                'message': 'Login successful',
                'admin_name': admin_name,
                'admin_id': request.admin_id
            }
        else:
            return {
                'success': False,
                'message': result
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/auth/change-password")
async def change_admin_password(request: AdminPasswordChange, admin_id: str = Depends(get_current_admin)):
    """Change admin password"""
    try:
        result = db.change_admin_id_password(
            request.old_id,
            request.old_password,
            request.new_id,
            request.new_password,
            request.confirm_password
        )

        if 'updated' in result:
            return {
                'success': True,
                'message': result
            }
        else:
            return {
                'success': False,
                'message': result
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# person management endpoints
@app.get("/api/people")
async def get_people(admin_id: str = Depends(get_current_admin)):
    """Get all registered people with complete information"""
    try:
        person_ids = db.get_all_registration_ids_list()
        people = []
        skipped_count = 0

        # Use batch lookup for better performance (single query instead of 3 per person)
        person_data_batch = db.get_person_data_batch(person_ids)

        for idx, person_id in enumerate(person_ids):
            person_data = person_data_batch.get(person_id)

            # Skip people with missing data
            if not person_data or not person_data.get('name'):
                skipped_count += 1
                continue

            person_name = person_data['name']
            person_title = person_data.get('title', '')
            person_registration = person_data.get('registration_id', '')

            # Check if reference image exists (support both single and multi-photo formats)
            image_path = f'images/{person_id}.png'
            if not os.path.exists(image_path):
                image_path = f'images/{person_id}%1.png'

            has_image = os.path.exists(image_path)

            # Add timestamp for cache busting
            image_url = None
            if has_image:
                file_mtime = int(os.path.getmtime(image_path))
                image_url = f'/api/people/{person_id}/image?t={file_mtime}'

            # Count total photos for this person
            photo_files = []
            additional_photos = []
            if os.path.exists('images'):
                for filename in os.listdir('images'):
                    # Match both formats: person_id.png (legacy) and person_id%N.png (multi-photo)
                    if filename.startswith(f'{person_id}.png') or filename.startswith(f'{person_id}%'):
                        # Skip non-image files (like subdirectories)
                        if not filename.endswith('.png'):
                            continue
                        photo_files.append(filename)
                        # Don't count the primary photo as "additional"
                        # Primary photo is either person_id.png or person_id%1.png
                        if filename != f'{person_id}.png' and filename != f'{person_id}%1.png':
                            additional_photos.append(filename)

            people.append({
                'id': person_id,
                'name': person_name,
                'title': person_title or '',
                'has_image': has_image,
                'cvent_registration_number': person_registration,
                'image_path': image_url,
                'total_photos': len(photo_files),
                'additional_photos_count': len(additional_photos)
            })

        return {
            'success': True,
            'people': people,
            'total': len(people),
            'total_in_db': len(person_ids),
            'skipped': skipped_count
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/people/currently-recognized")
async def get_currently_recognized_stream():
    """
    PUBLIC ENDPOINT - SSE stream of currently recognized people
    Used by: Signature Aviation Drink App
    """

    def get_current_recognition_data():
        """Helper function to get current recognition status for all people"""
        global currently_recognized_people

        # Clean up expired recognitions first
        cleanup_expired_recognitions()

        current_time = time.time()
        detection_active = get_independent_detection_active()

        if currently_recognized_people:
            # Build list of all currently recognized people
            people_list = []

            for person_name, data in currently_recognized_people.items():
                time_since_last = current_time - data['last_seen']
                people_list.append({
                    'name': person_name,
                    'registration_id': data['registration'],
                    'last_seen': data['last_seen'],
                    'seconds_ago': time_since_last
                })

            return {
                'success': True,
                'detection_active': detection_active,
                'recognized': True,
                'people': people_list,
                'count': len(people_list)
            }
        else:
            # No one currently recognized
            return {
                'success': True,
                'detection_active': detection_active,
                'recognized': False,
                'people': [],
                'count': 0
            }

    async def event_stream():
        """SSE event generator"""
        global recognition_data_changed
        last_sent_data = None

        try:
            # Send initial data immediately
            current_data = get_current_recognition_data()
            data_json = json.dumps(current_data)
            yield f"data: {data_json}\n\n"
            last_sent_data = current_data

            while True:
                try:
                    # Check every 100ms for changes (more responsive)
                    await asyncio.sleep(0.1)

                    # Only check data if the flag indicates a change, or for periodic heartbeat
                    should_check = recognition_data_changed or (int(time.time() * 10) % 50 == 0)  # Every 5 seconds heartbeat

                    if should_check:
                        # Reset the flag
                        was_flagged = recognition_data_changed
                        recognition_data_changed = False

                        # Get current recognition data
                        current_data = get_current_recognition_data()

                        # Only send if data has actually changed
                        if current_data != last_sent_data:
                            data_json = json.dumps(current_data)
                            yield f"data: {data_json}\n\n"
                            last_sent_data = current_data

                except Exception as e:
                    error_data = {
                        'success': False,
                        'detection_active': get_independent_detection_active(),
                        'error': str(e),
                        'recognized': False,
                        'person': None
                    }
                    yield f"data: {json.dumps(error_data)}\n\n"
                    await asyncio.sleep(1)

        except asyncio.CancelledError:
            print("🔌 SSE client disconnected from currently-recognized stream")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control"
        }
    )

@app.get("/api/people/test-cycle")
#Test endpoint (can remove in production)
async def get_test_cycle_stream():
    """SSE stream that randomly cycles through all people in database for testing third-party integration"""

    async def event_stream():
        """SSE event generator that cycles through people"""
        import random

        try:
            while True:
                try:
                    # Get all people from database
                    person_ids = db.get_all_registration_ids_list()
                    all_people = []

                    for person_id in person_ids:
                        person_name = db.get_person_name(person_id)
                        person_registration = db.get_registration_id(person_id)
                        if person_name:
                            all_people.append({
                                'person_name': person_name,
                                'person_registration': person_registration
                            })

                    if not all_people:
                        # No people in database
                        data = {
                            'success': True,
                            'detection_active': False,
                            'recognized': False,
                            'people': [],
                            'count': 0,
                            'test_mode': True
                        }
                        yield f"data: {json.dumps(data)}\n\n"
                        await asyncio.sleep(3)  # Wait 3 seconds before next check
                        continue

                    # Randomly select a person
                    selected_person = random.choice(all_people)

                    # Format the response to match the currently-recognized endpoint
                    data = {
                        'success': True,
                        'detection_active': False,  # Always false for test mode
                        'recognized': True,
                        'people': [{
                            'name': selected_person['person_name'],
                            'registration_id': selected_person['person_registration'],
                            'last_seen': time.time(),
                            'seconds_ago': 0
                        }],
                        'count': 1,
                        'test_mode': True
                    }

                    yield f"data: {json.dumps(data)}\n\n"

                    # Wait 2-5 seconds before showing next person (randomized)
                    wait_time = random.uniform(2.0, 5.0)
                    await asyncio.sleep(wait_time)

                except Exception as e:
                    error_data = {
                        'success': False,
                        'detection_active': False,
                        'error': str(e),
                        'recognized': False,
                        'people': [],
                        'count': 0,
                        'test_mode': True
                    }
                    yield f"data: {json.dumps(error_data)}\n\n"
                    await asyncio.sleep(1)

        except asyncio.CancelledError:
            print("🔌 SSE client disconnected from test-cycle stream")

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Cache-Control"
        }
    )

@app.post("/api/people/register")
async def register_person(request: personRegistration, admin_id: str = Depends(get_current_admin)):
    """Register a new person with auto-generated UUID"""
    try:
        # Check if registration ID already exists
        if db.check_registration_exists(request.person_registration):
            return {
                'success': False,
                'message': f'Registration ID "{request.person_registration}" already exists. Please use a unique registration ID.'
            }

        # Generate a unique UUID for the person
        person_id = str(uuid.uuid4())

        # Decode base64 image
        if request.image_data.startswith('data:image'):
            image_data = request.image_data.split(',')[1]
        else:
            image_data = request.image_data

        image_bytes = base64.b64decode(image_data)
        image = Image.open(BytesIO(image_bytes))

        # Fix EXIF orientation (handles sideways/rotated images from phones)
        image = ImageOps.exif_transpose(image)

        # Convert to OpenCV format
        image_cv = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

        # Use the registration-specific face recognizer with higher sensitivity
        _, faces = face_recognizer.recognize_face_for_registration(image_cv, f"{person_id}.png")

        if faces is None or len(faces) == 0:
            return {
                'success': False,
                'message': 'No face detected in the image'
            }

        if len(faces) > 1:
            return {
                'success': False,
                'message': 'Multiple faces detected. Please use an image with only one face.'
            }

        # Crop face with padding (same as bulk upload process)
        face = faces[0]
        x, y, w, h = face.bbox

        # Add padding around the face (20% on each side, same as bulk upload)
        padding = 0.2
        x_pad = int(w * padding)
        y_pad = int(h * padding)

        # Calculate new boundaries with padding
        x1 = max(0, x - x_pad)
        y1 = max(0, y - y_pad)
        x2 = min(image_cv.shape[1], x + w + x_pad)
        y2 = min(image_cv.shape[0], y + h + y_pad)

        # Crop the face with padding
        cropped_face = image_cv[y1:y2, x1:x2]

        # Save person to database (UUID ensures uniqueness, so no conflict possible)
        db_result = db.insert_into_registrations(person_id, request.person_name, request.person_title, request.person_registration)

        if 'already exist' in db_result:
            # This should theoretically never happen with UUID, but handle it just in case
            return {
                'success': False,
                'message': 'Unexpected ID collision occurred, please try again'
            }

        # Save cropped face image (consistent with bulk upload)
        os.makedirs('images', exist_ok=True)
        image_path = f'images/{person_id}.png'
        cv2.imwrite(image_path, cropped_face)

        # Generate thumbnail for faster loading in UI
        generate_thumbnail(person_id)

        # Efficiently add pre-cropped photo to FAISS database (skips redundant face detection)
        success = face_recognizer.add_pre_cropped_photo_to_database(person_id, image_path)

        if not success:
            # Clean up on failure
            try:
                os.remove(image_path)
                db.delete_registration(person_id)
            except:
                pass
            return {
                'success': False,
                'message': 'Failed to add person to recognition database'
            }

        return {
            'success': True,
            'message': 'Person registered successfully',
            'person_id': person_id,
            'person_registartion': request.person_registration,
            'person_name': request.person_name,
            'person_title': request.person_title
        }

    except Exception as e:
        return {
            'success': False,
            'message': f'Registration failed: {str(e)}'
        }

@app.post("/api/people/upload-csv-stream")
async def upload_csv_bulk_registration_stream(file: UploadFile = File(...), admin_id: str = Depends(get_current_admin)):
    """Process CSV file for bulk person registration with progress streaming"""

    # Validate file is CSV
    if not file.filename.endswith('.csv'):
        async def error_generator():
            yield f"event: error\ndata: {json.dumps({'error': 'File must be a CSV file'})}\n\n"
        return EventSourceResponse(error_generator())

    # Read CSV content before creating the generator
    try:
        content = await file.read()
        csv_content = content.decode('utf-8')
    except Exception as e:
        async def error_generator():
            yield f"event: error\ndata: {json.dumps({'error': f'Failed to read file: {str(e)}'})}\n\n"
        return EventSourceResponse(error_generator())

    # Create the streaming generator with the CSV content
    async def generate_progress():
        try:
            # Process CSV with progress streaming
            async for event in process_csv_with_progress_streaming(
                csv_content,
                face_recognizer,
                db,
                generate_thumbnail
            ):
                yield event

        except Exception as e:
            import traceback
            error_details = f'Failed to process CSV: {str(e)}\nTraceback: {traceback.format_exc()}'
            print(f"CSV Processing Error: {error_details}")
            yield f"event: error\ndata: {json.dumps({'error': f'Failed to process CSV: {str(e)}'})}\n\n"

    return EventSourceResponse(generate_progress())

@app.get("/api/people/csv-requirements")
async def get_csv_requirements(admin_id: str = Depends(get_current_admin)):
    """Get the required CSV column headers for bulk upload"""
    return {
        'success': True,
        'required_columns': [
            "First_Name",
            "Last_Name",
            "Title",
            "Registration_Confirmation_Number",
            "Image_URL"
        ],
        'notes': [
            "First_Name and Last_Name will be combined into full name",
            "Image_URL is optional but recommended for face recognition",
            "CSV must have headers in the first row",
            "Empty Image_URL fields are allowed"
        ]
    }

@app.post("/api/people/{person_id}/add-photo")
async def add_additional_photo(person_id: str, request: AdditionalPhotoUpload, admin_id: str = Depends(get_current_admin)):
    """Add an additional photo template for an existing person"""
    try:
        # Verify person exists
        person_name = db.get_person_name(person_id)
        if not person_name:
            return {
                'success': False,
                'message': 'Person not found'
            }

        # Decode base64 image
        if request.image_data.startswith('data:image'):
            image_data = request.image_data.split(',')[1]
        else:
            image_data = request.image_data

        image_bytes = base64.b64decode(image_data)
        image = Image.open(BytesIO(image_bytes))

        # Fix EXIF orientation (handles sideways/rotated images from phones)
        image = ImageOps.exif_transpose(image)

        # Convert to OpenCV format
        image_cv = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

        # Use registration-specific face recognizer with higher sensitivity
        _, faces = face_recognizer.recognize_face_for_registration(image_cv, f"{person_id}_temp.png")

        if faces is None or len(faces) == 0:
            return {
                'success': False,
                'message': 'No face detected in the image'
            }

        if len(faces) > 1:
            return {
                'success': False,
                'message': 'Multiple faces detected. Please use an image with only one face.'
            }

        # Crop face with padding (same as initial registration)
        face = faces[0]
        x, y, w, h = face.bbox

        # Add padding around the face (20% on each side, same as initial registration)
        padding = 0.2
        x_pad = int(w * padding)
        y_pad = int(h * padding)

        # Calculate new boundaries with padding
        x1 = max(0, x - x_pad)
        y1 = max(0, y - y_pad)
        x2 = min(image_cv.shape[1], x + w + x_pad)
        y2 = min(image_cv.shape[0], y + h + y_pad)

        # Crop the face with padding
        cropped_face = image_cv[y1:y2, x1:x2]

        # Normalize existing photos to %N format if needed
        os.makedirs('images', exist_ok=True)
        legacy_photo = f'images/{person_id}.png'
        if os.path.exists(legacy_photo):
            # Rename legacy format to %1 format for consistency
            new_name = f'images/{person_id}%1.png'
            if not os.path.exists(new_name):  # Safety check
                os.rename(legacy_photo, new_name)
                print(f"Normalized legacy photo: {person_id}.png → {person_id}%1.png")

        # Find the highest numbered photo to determine next number
        existing_photos = [f for f in os.listdir('images') if f.startswith(f'{person_id}%') and f.endswith('.png')]
        if existing_photos:
            # Extract numbers from filenames like "person_id%2.png"
            numbers = []
            for photo in existing_photos:
                try:
                    num = int(photo.split('%')[1].replace('.png', ''))
                    numbers.append(num)
                except:
                    pass
            next_number = max(numbers) + 1 if numbers else 1
        else:
            next_number = 1

        # Save cropped face image with proper numbering (consistent with initial registration)
        image_filename = f'{person_id}%{next_number}.png'
        image_path = f'images/{image_filename}'
        cv2.imwrite(image_path, cropped_face)

        # Efficiently add pre-cropped photo to FAISS database (skips redundant face detection)
        success = face_recognizer.add_pre_cropped_photo_to_database(person_id, image_path)

        if not success:
            # Clean up the saved image if FAISS add failed
            try:
                os.remove(image_path)
            except:
                pass
            return {
                'success': False,
                'message': 'Failed to add photo to recognition database'
            }

        return {
            'success': True,
            'message': 'Additional photo added successfully',
            'person_id': person_id,
            'total_photos': next_number
        }

    except Exception as e:
        return {
            'success': False,
            'message': f'Failed to add additional photo: {str(e)}'
        }

@app.get("/api/people/{person_id}/photos")
async def get_person_photos(person_id: str, admin_id: str = Depends(get_current_admin)):
    """Get all photo URLs for a specific person"""
    try:
        # Verify person exists
        person_name = db.get_person_name(person_id)
        if not person_name:
            return {
                'success': False,
                'message': 'Person not found'
            }

        # Collect all photo files for this person
        photos = []
        if os.path.exists('images'):
            for filename in os.listdir('images'):
                # Match both formats: person_id.png (legacy) and person_id%N.png (multi-photo)
                if (filename.startswith(f'{person_id}.png') or filename.startswith(f'{person_id}%')) and filename.endswith('.png'):
                    photo_path = f'images/{filename}'
                    if os.path.exists(photo_path):
                        file_mtime = int(os.path.getmtime(photo_path))
                        # Extract photo number for sorting
                        if '%' in filename:
                            try:
                                photo_number = int(filename.split('%')[1].replace('.png', ''))
                            except:
                                photo_number = 0
                        else:
                            photo_number = 1  # Legacy format is treated as photo #1

                        photos.append({
                            'filename': filename,
                            'url': f'/api/people/{person_id}/photo/{quote(filename)}?t={file_mtime}',
                            'photo_number': photo_number,
                            'is_primary': filename == f'{person_id}.png' or filename == f'{person_id}%1.png'
                        })

        # Sort photos by number
        photos.sort(key=lambda x: x['photo_number'])

        return {
            'success': True,
            'person_id': person_id,
            'person_name': person_name,
            'photos': photos,
            'total': len(photos)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/people/{person_id}/photo/{filename:path}")
async def get_person_photo_file(person_id: str, filename: str):
    """
    Serve a specific photo file for a person
    PUBLIC ENDPOINT - No authentication required (secured by obscurity - requires knowing person_id + filename)
    Used by: Settings page photo carousel, Welcome screen
    """
    try:
        # FastAPI may double-decode in some proxy setups, so ensure we have the right filename
        # Handle both encoded and decoded versions
        decoded_filename = unquote(filename) if '%' in filename and not filename.startswith(f'{person_id}%') else filename

        # Security: Verify the filename belongs to this person
        if not (decoded_filename.startswith(f'{person_id}.png') or decoded_filename.startswith(f'{person_id}%')):
            raise HTTPException(status_code=403, detail="Unauthorized access to photo")

        # Security: Prevent directory traversal
        if '..' in decoded_filename or '/' in decoded_filename:
            raise HTTPException(status_code=403, detail="Invalid filename")

        photo_path = f'images/{decoded_filename}'
        if not os.path.exists(photo_path):
            raise HTTPException(status_code=404, detail="Photo not found")

        return FileResponse(photo_path, media_type="image/png")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/people/{person_id}/photos/{filename}")
async def delete_person_photo(person_id: str, filename: str, admin_id: str = Depends(get_current_admin)):
    """Delete a specific photo for a person and refresh FAISS database"""
    try:
        # Verify person exists
        person_name = db.get_person_name(person_id)
        if not person_name:
            return {
                'success': False,
                'message': 'Person not found'
            }

        # Security: Verify the filename belongs to this person
        if not (filename.startswith(f'{person_id}.png') or filename.startswith(f'{person_id}%')):
            return {
                'success': False,
                'message': 'Unauthorized: Photo does not belong to this person'
            }

        # Security: Prevent directory traversal
        if '..' in filename or '/' in filename:
            return {
                'success': False,
                'message': 'Invalid filename'
            }

        # Check if photo exists
        photo_path = f'images/{filename}'
        if not os.path.exists(photo_path):
            return {
                'success': False,
                'message': 'Photo not found'
            }

        # Prevent deletion of primary photo (first uploaded photo)
        # Primary photo is either person_id.png or person_id%1.png
        is_primary = filename == f'{person_id}.png' or filename == f'{person_id}%1.png'
        if is_primary:
            return {
                'success': False,
                'message': 'Cannot delete the primary photo. Each person must have at least one recognizable photo.'
            }

        # Count total photos before deletion
        existing_photos = []
        if os.path.exists('images'):
            for f in os.listdir('images'):
                if (f.startswith(f'{person_id}.png') or f.startswith(f'{person_id}%')) and f.endswith('.png'):
                    existing_photos.append(f)

        # Remove from FAISS database first (more efficient than rebuilding from disk)
        try:
            print(f"🗑️ Removing photo from FAISS database: {filename}")
            faiss_removed = face_recognizer.remove_photo_from_database(person_id, filename)
            if faiss_removed:
                print(f"✅ Photo removed from FAISS database efficiently")
            else:
                print(f"⚠️ Photo not found in FAISS database (may have been out of sync)")
        except Exception as e:
            print(f"⚠️ Error removing from FAISS database: {e}")
            # Continue with file deletion even if FAISS removal fails

        # Delete the photo file from disk
        try:
            os.remove(photo_path)
            print(f"✅ Deleted photo file: {filename}")
        except Exception as e:
            return {
                'success': False,
                'message': f'Failed to delete photo file: {str(e)}'
            }

        # Calculate remaining photos
        remaining_photos = [f for f in existing_photos if f != filename]

        return {
            'success': True,
            'message': 'Photo deleted successfully and FAISS database updated',
            'person_id': person_id,
            'deleted_photo': filename,
            'remaining_photos': len(remaining_photos)
        }

    except Exception as e:
        return {
            'success': False,
            'message': f'Failed to delete photo: {str(e)}'
        }

@app.delete("/api/people/{person_id}")
async def delete_person(person_id: str, admin_id: str = Depends(get_current_admin)):
    """Delete a person and all their photos"""
    try:
        # Verify person exists in database first
        person_name = db.get_person_name(person_id)
        if not person_name:
            return {
                'success': False,
                'message': 'Person not found in database'
            }

        # Remove from FAISS database and delete image files
        # (remove_person handles: image files, FAISS index, person mapping, cache)
        try:
            face_recognizer.remove_person(person_id)
            faiss_message = ' and removed from recognition database'
        except Exception as e:
            print(f"⚠️ Error in remove_person: {e}")
            import traceback
            traceback.print_exc()
            # Continue with deletion even if FAISS removal fails
            faiss_message = ' (warning: FAISS removal had issues)'

        # Delete thumbnails (not handled by remove_person)
        deleted_thumbnails = 0
        if os.path.exists('images/thumbnails'):
            for filename in os.listdir('images/thumbnails'):
                # Match thumbnail files like {person_id}_150.jpg
                if filename.startswith(f'{person_id}_') and filename.endswith('.jpg'):
                    thumbnail_path = os.path.join('images/thumbnails', filename)
                    try:
                        os.remove(thumbnail_path)
                        deleted_thumbnails += 1
                    except Exception as e:
                        print(f"⚠️ Error deleting thumbnail {filename}: {e}")

        # Delete from attendance database
        # Note: delete_registration tries to delete the image file, but we already did that
        # So we ignore its return value and verify deletion by checking if person still exists
        try:
            db.delete_registration(person_id)
        except Exception as e:
            print(f"⚠️ Error deleting from database: {e}")

        # Verify person was deleted by checking if they still exist
        person_still_exists = db.get_person_name(person_id)
        if not person_still_exists:
            message = f'Person "{person_name}" deleted successfully{faiss_message}'
            return {
                'success': True,
                'message': message
            }
        else:
            return {
                'success': False,
                'message': 'Failed to delete person from database'
            }
    except Exception as e:
        print(f"❌ Delete person error: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/people")
async def delete_all_people(admin_id: str = Depends(get_current_admin)):
    """Delete all people from the database"""
    try:
        person_ids = db.get_all_registration_ids_list()
        deleted_count = 0
        failed_deletions = []
        deleted_photos = []

        # Delete from database and remove photo files
        for person_id in person_ids:
            result = db.delete_registration(person_id)
            if result:
                deleted_count += 1

                # Delete all photo files for this person
                if os.path.exists('images'):
                    for filename in os.listdir('images'):
                        # Match both single-photo ({person_id}.png) and multi-photo ({person_id}%1.png, etc.)
                        if (filename == f'{person_id}.png' or
                            (filename.startswith(f'{person_id}%') and filename.endswith('.png'))):
                            file_path = os.path.join('images', filename)
                            try:
                                os.remove(file_path)
                                deleted_photos.append(filename)
                            except Exception as e:
                                print(f"⚠️ Error deleting photo {filename}: {e}")

                # Delete thumbnails for this person
                if os.path.exists('images/thumbnails'):
                    for filename in os.listdir('images/thumbnails'):
                        # Match thumbnail files like {person_id}_150.jpg
                        if filename.startswith(f'{person_id}_') and filename.endswith('.jpg'):
                            thumbnail_path = os.path.join('images/thumbnails', filename)
                            try:
                                os.remove(thumbnail_path)
                            except Exception as e:
                                print(f"⚠️ Error deleting thumbnail {filename}: {e}")
            else:
                failed_deletions.append(person_id)

        # Completely reset FAISS database (more reliable than trying to remove by ID)
        if deleted_count > 0:
            print("🔄 Resetting FAISS database after deleting all people...")

            # Create a fresh, empty FAISS database
            from database.face_db import FaceDatabase
            from pathlib import Path
            face_recognizer.face_database = FaceDatabase(
                embedding_size=512,
                db_path=str(Path("system/faiss_database")),
                max_workers=4
            )

            # Clear person mapping
            face_recognizer.person_id_to_name.clear()

            # Save the empty database to cache
            face_recognizer.face_database.save()
            face_recognizer._save_person_mapping()

            print(f"✅ FAISS database completely reset (empty)")

        if len(failed_deletions) == 0:
            return {
                'success': True,
                'message': f'All {deleted_count} people deleted successfully',
                'deleted_count': deleted_count,
                'deleted_photos': len(deleted_photos)
            }
        else:
            return {
                'success': False,
                'message': f'Deleted {deleted_count} people, but failed to delete {len(failed_deletions)} people',
                'deleted_count': deleted_count,
                'failed_deletions': failed_deletions,
                'deleted_photos': len(deleted_photos)
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/people/{person_id}/image")
async def get_person_image(person_id: str):
    """
    Get a person's thumbnail image - optimized for list views
    PUBLIC ENDPOINT - No authentication required (secured by obscurity)
    Used by: Settings page person list
    """
    try:
        # Support both single-photo and multi-photo formats
        image_path = f'images/{person_id}.png'
        if not os.path.exists(image_path):
            image_path = f'images/{person_id}%1.png'
            if not os.path.exists(image_path):
                raise HTTPException(status_code=404, detail="Person image not found")

        # Fixed thumbnail size for consistency
        size = 150
        thumbnail_path = f'images/thumbnails/{person_id}_{size}.jpg'
        file_mtime = os.path.getmtime(image_path)

        # Generate thumbnail only if it doesn't exist or is outdated
        # (for backward compatibility with users registered before thumbnail generation was added)
        if not os.path.exists(thumbnail_path):
            generate_thumbnail(person_id, size)
        else:
            # Check if thumbnail is outdated
            thumb_mtime = os.path.getmtime(thumbnail_path)
            if thumb_mtime < file_mtime:
                generate_thumbnail(person_id, size)

        # Return thumbnail with proper headers
        etag = f'"{person_id}-{size}-{int(file_mtime)}"'

        return FileResponse(
            thumbnail_path,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "public, max-age=3600",  # Cache for 1 hour
                "Access-Control-Allow-Origin": "*",
                "ETag": etag,
                "Last-Modified": time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime(file_mtime))
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Face recognition endpoints
@app.post("/api/recognition/detect")
async def detect_faces(request: FaceDetectionRequest, admin_id: str = Depends(get_current_admin)):
    """Detect and recognize faces in an image"""
    try:
        # Decode base64 image
        if request.image_data.startswith('data:image'):
            image_data = request.image_data.split(',')[1]
        else:
            image_data = request.image_data

        image_bytes = base64.b64decode(image_data)
        image = Image.open(BytesIO(image_bytes))
        frame = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

        # Use the face recognizer
        endpoint_features, faces = face_recognizer.recognize_face(frame)

        results = []
        if faces is not None:
            for i, face_detection in enumerate(faces):
                # Get bounding box from FaceDetection object
                x1, y1, w, h = face_detection.bbox
                x2, y2 = x1 + w, y1 + h

                result = {
                    'bbox': [x1, y1, x2, y2],
                    'confidence': float(face_detection.confidence),
                    'quality_score': float(face_detection.quality_score),
                    'face_area': int(face_detection.face_area),
                    'is_frontal': bool(face_detection.is_frontal)
                }

                # Check if we have features and can match
                if i < len(endpoint_features) and face_recognizer.dictionary:
                    feature = endpoint_features[i]
                    best_match = None
                    highest_score = 0

                    # Compare with all known faces
                    dictionary_copy = dict(face_recognizer.dictionary)
                    for person_id, ref_feature in dictionary_copy.items():
                        score = face_recognizer.face_recognizer.match(feature, ref_feature)
                        if score > face_recognizer.threshold and score > highest_score:
                            highest_score = score
                            person_name = db.get_person_name(person_id)
                            person_title = db.get_person_title(person_id)
                            best_match = {
                                'person_id': person_id,
                                'person_name': person_name,
                                'person_title': person_title,
                                'confidence': float(score)
                            }

                    if best_match:
                        result.update({
                            'person_id': best_match['person_id'],
                            'person_name': best_match['person_name'],
                            'person_title': best_match['person_title'],
                            'match_confidence': best_match['confidence'],
                            'recognized': True
                        })
                    else:
                        result.update({
                            'person_id': 'UNKNOWN',
                            'person_name': 'Unknown Person',
                            'match_confidence': 0.0,
                            'recognized': False
                        })
                else:
                    result.update({
                        'person_id': 'UNKNOWN',
                        'person_name': 'Unknown Person',
                        'match_confidence': 0.0,
                        'recognized': False
                    })

                results.append(result)

        return {
            'success': True,
            'faces': results,
            'timestamp': get_current_datetime_other_format()
        }

    except Exception as e:
        return {
            'success': False,
            'message': f'Recognition failed: {str(e)}',
            'faces': []
        }

# Removed /api/recognition/latest endpoint - welcome screens use WebSocket events for real-time recognition

# Camera management endpoints
@app.get("/api/camera/settings")
async def get_camera_settings(admin_id: str = Depends(get_current_admin)):
    """Get current camera settings"""
    # Config updated to use webcam source
    try:
        camera_config = config_manager.get_camera_config()
        return {
            'success': True,
            'source': camera_config.get('source', 'webcam'),
            'device_id': camera_config.get('device_id'),
            'rtsp_url': camera_config.get('rtsp_url')
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/camera/settings")
async def update_camera_settings(request: CameraSettings, admin_id: str = Depends(get_current_admin)):
    """Update camera settings"""
    try:
        # Update config file
        success = config_manager.set_camera_config(
            source=request.source,
            device_id=request.device_id,
            rtsp_url=request.rtsp_url
        )

        # Also save to legacy pickle file if RTSP
        if request.source == 'rtsp' and request.rtsp_url:
            save_rtsp_settings(request.rtsp_url)
        elif request.source != 'rtsp':
            save_rtsp_settings('')  # Clear RTSP settings

        if success:
            return {
                'success': True,
                'message': 'Camera settings updated successfully'
            }
        else:
            return {
                'success': False,
                'message': 'Failed to save camera settings'
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Face detection configuration endpoints (MediaPipe-compatible API)
@app.get("/api/mediapipe/settings")
async def get_mediapipe_settings(admin_id: str = Depends(get_current_admin)):
    """Get current face detection settings"""
    try:
        mediapipe_config = config_manager.get_mediapipe_config()
        performance_stats = face_recognizer.get_performance_stats()

        # Include current face recognizer settings
        current_settings = mediapipe_config.copy()
        current_settings['include_landmarks'] = face_recognizer.include_landmarks

        return {
            'success': True,
            'settings': current_settings,
            'performance': {
                'avg_detection_time_ms': performance_stats.get('avg_detection_time_ms', 0),
                'registered_faces': performance_stats.get('registered_faces', 0),
                'total_detections': performance_stats.get('total_detections', 0)
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/mediapipe/settings")
async def update_mediapipe_settings(request: DetectionSettings, admin_id: str = Depends(get_current_admin)):
    """Update MediaPipe settings"""
    try:
        # Update config file
        success = config_manager.set_mediapipe_config(
            detection_confidence=request.detection_confidence,
            tracking_confidence=request.tracking_confidence,
            max_faces=request.max_faces,
            refine_landmarks=request.refine_landmarks,
            unlimited_faces=request.unlimited_faces
        )

        if success:
            # Apply settings to face recognizer
            face_recognizer.configure_mediapipe(
                detection_confidence=request.detection_confidence,
                tracking_confidence=request.tracking_confidence,
                max_faces=request.max_faces,
                refine_landmarks=request.refine_landmarks,
                unlimited_faces=request.unlimited_faces,
                include_landmarks=request.include_landmarks
            )

            return {
                'success': True,
                'message': 'MediaPipe settings updated successfully'
            }
        else:
            return {
                'success': False,
                'message': 'Failed to save MediaPipe settings'
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/mediapipe/presets")
async def get_mediapipe_presets(admin_id: str = Depends(get_current_admin)):
    """Get predefined MediaPipe configuration presets"""
    try:
        presets = {
            'small_groups': {
                'name': '👤 Small Groups (< 5 people)',
                'description': 'Optimized for 1-4 people with maximum accuracy and distance detection (up to 10+ feet)',
                'settings': {
                    'detection_confidence': 0.15,  # Very low threshold for maximum distance
                    'tracking_confidence': 0.7,    # High stability for fewer faces
                    'max_faces': 4,                 # Focus on small groups
                    'refine_landmarks': True,       # Maximum landmark precision
                    'unlimited_faces': False,
                    'recognition_threshold': 0.4    # Higher threshold for better accuracy
                }
            },
            'large_groups': {
                'name': '👥 Large Groups (5+ people)',
                'description': 'Optimized for crowds with batch processing - handles 20+ faces efficiently',
                'settings': {
                    'detection_confidence': 0.25,  # Slightly higher for crowd stability
                    'tracking_confidence': 0.5,    # Balanced for multiple faces
                    'max_faces': 20,               # Efficient with batch processing
                    'refine_landmarks': True,       # Keep quality landmarks
                    'unlimited_faces': False,
                    'recognition_threshold': 0.35   # Slightly lower for crowd flexibility
                }
            }
        }

        return {
            'success': True,
            'presets': presets
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/mediapipe/apply-preset")
async def apply_mediapipe_preset(request: dict, admin_id: str = Depends(get_current_admin)):
    """Apply a predefined MediaPipe configuration preset"""
    try:
        preset_name = request.get('preset')
        presets_response = await get_mediapipe_presets(admin_id=admin_id)
        presets = presets_response['presets']

        if preset_name not in presets:
            return {
                'success': False,
                'message': f'Preset "{preset_name}" not found'
            }

        preset_settings = presets[preset_name]['settings']

        # Extract recognition settings from preset
        recognition_threshold = preset_settings.pop('recognition_threshold', None)

        # Apply preset to config (without recognition_threshold as it's not a mediapipe setting)
        success = config_manager.set_mediapipe_config(**preset_settings)

        if success:
            # Apply to face recognizer
            face_recognizer.configure_mediapipe(**preset_settings)

            # Apply recognition threshold if specified
            if recognition_threshold is not None:
                face_recognizer.threshold = recognition_threshold
                print(f"🎯 Applied recognition threshold: {recognition_threshold}")

            # Re-add recognition_threshold to the response
            response_settings = preset_settings.copy()
            if recognition_threshold is not None:
                response_settings['recognition_threshold'] = recognition_threshold

            return {
                'success': True,
                'message': f'Applied preset: {presets[preset_name]["name"]}',
                'applied_settings': response_settings
            }
        else:
            return {
                'success': False,
                'message': 'Failed to apply preset'
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/recognition/settings")
async def get_recognition_settings(admin_id: str = Depends(get_current_admin)):
    """Get current recognition threshold settings"""
    try:
        return {
            'success': True,
            'settings': {
                'recognition_threshold': face_recognizer.threshold,
                'face_quality_threshold': face_recognizer.face_quality_threshold
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/recognition/settings")
async def update_recognition_settings(settings: RecognitionSettings, admin_id: str = Depends(get_current_admin)):
    """Update recognition threshold settings for better accuracy"""
    try:
        updated = False

        if settings.recognition_threshold is not None:
            face_recognizer.threshold = settings.recognition_threshold
            updated = True

        if settings.face_quality_threshold is not None:
            face_recognizer.face_quality_threshold = settings.face_quality_threshold
            updated = True

        if updated:
            return {
                'success': True,
                'message': 'Recognition settings updated successfully',
                'current_settings': {
                    'recognition_threshold': face_recognizer.threshold,
                    'face_quality_threshold': face_recognizer.face_quality_threshold
                }
            }
        else:
            return {
                'success': False,
                'message': 'No settings provided to update'
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/camera/devices")
async def get_camera_devices(admin_id: str = Depends(get_current_admin)):
    """Camera devices should be enumerated by the browser, not the backend.
    This endpoint returns empty to respect browser camera permissions."""
    try:
        # Return empty device list - the frontend will handle camera enumeration
        # via navigator.mediaDevices.enumerateDevices() which respects browser permissions
        devices = []

        print("📱 Camera enumeration delegated to browser (respects permissions)")

        return {
            'success': True,
            'devices': devices
        }
    except Exception as e:
        print(f"❌ Error enumerating devices: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/camera/test")
async def test_camera(request: CameraSettings, admin_id: str = Depends(get_current_admin)):
    """Test camera connection"""
    try:
        print(f"🔍 Testing camera - source: {request.source}, rtsp_url: {request.rtsp_url}")

        # Support webcam, rtsp, and legacy device sources
        if request.source == 'rtsp':
            if not request.rtsp_url:
                return {
                    'success': False,
                    'message': 'RTSP URL is required for RTSP camera source'
                }
            source = request.rtsp_url
            print(f"📡 Testing RTSP camera: {request.rtsp_url}")
        elif request.source in ['webcam', 'device', 'default']:
            # Use device_id if specified, otherwise default to 0
            if request.device_id:
                try:
                    # Check if it's in "index:deviceId" format from camera testing
                    if ':' in request.device_id:
                        camera_index, _ = request.device_id.split(':', 1)
                        source = int(camera_index)
                        print(f"📹 Testing specific camera index: {source}")
                    else:
                        source = int(request.device_id)  # Try to convert to int for device index
                        print(f"📹 Testing webcam device index: {source}")
                except ValueError:
                    # If device_id is not a number, fall back to default camera
                    source = 0
                    print(f"📹 Device {request.device_id[:12]}... → falling back to camera index: {source}")
            else:
                source = 0  # Default webcam
                print(f"📹 Testing default webcam (index 0)")
        else:
            return {
                'success': False,
                'message': f'Unsupported camera source: {request.source}. Only webcam, device, default, and rtsp are supported.'
            }

        # Test the camera
        cap = cv2.VideoCapture(source)

        try:
            if cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    print(f"✅ Camera test successful for source: {source}")
                    return {
                        'success': True,
                        'message': f'Camera connection successful (source: {source})'
                    }
                else:
                    print(f"❌ Camera opened but couldn't read frame from source: {source}")
                    # In Docker/headless environments, this is expected for non-RTSP sources
                    if request.source != 'rtsp':
                        return {
                            'success': True,
                            'message': f'Camera configuration saved. Testing may be limited in Docker/headless environments. (source: {source})'
                        }
                    else:
                        return {
                            'success': False,
                            'message': f'Camera opened but no video signal (source: {source})'
                        }
            else:
                print(f"❌ Couldn't open camera source: {source}")
                # In Docker/headless environments, this is expected for non-RTSP sources
                if request.source != 'rtsp':
                    return {
                        'success': True,
                        'message': f'Camera configuration saved. Testing may be limited in Docker/headless environments. (source: {source})'
                    }
                else:
                    return {
                        'success': False,
                        'message': f'Failed to open camera (source: {source})'
                    }
        finally:
            cap.release()

    except Exception as e:
        print(f"❌ Camera test exception: {str(e)}")
        return {
            'success': False,
            'message': f'Camera test failed: {str(e)}'
        }

# Removed complex camera enumeration endpoint

# Display settings endpoints
@app.get("/api/display/settings")
async def get_display_settings():
    """
    Get current display settings
    PUBLIC ENDPOINT - No authentication required
    Used by: Welcome screen popup for styling
    """
    try:
        display_config = config_manager.get_display_config()
        return {
            'success': True,
            'timer': display_config.get('timer', 5),
            'background_color': display_config.get('background_color', '#FFE8D4'),
            'font_color': display_config.get('font_color', '#032F5C'),
            'cloud_color': display_config.get('cloud_color', '#4ECDC4'),
            'use_background_image': display_config.get('use_background_image', False),
            'has_background_image': bool(display_config.get('background_image') and
                                       os.path.exists(display_config.get('background_image', ''))),
            'font_family': display_config.get('font_family', 'Inter'),
            'font_size': display_config.get('font_size', 'medium'),
            'bubble_size': display_config.get('bubble_size', 'medium')
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/display/settings")
async def update_display_settings(request: DisplaySettings, admin_id: str = Depends(get_current_admin)):
    """Update display settings"""
    try:
        success = config_manager.set_display_config(
            timer=request.timer,
            background_color=request.background_color,
            font_color=request.font_color,
            cloud_color=request.cloud_color,
            use_background_image=request.use_background_image,
            background_image=request.background_image,
            font_family=request.font_family,
            font_size=request.font_size,
            bubble_size=request.bubble_size
        )

        if success:
            # Broadcast updated settings to all connected welcome screens
            if welcome_screens:
                updated_settings = {
                    'timer': request.timer,
                    'background_color': request.background_color,
                    'font_color': request.font_color,
                    'cloud_color': request.cloud_color,
                    'use_background_image': request.use_background_image,
                    'font_family': request.font_family,
                    'font_size': request.font_size,
                    'bubble_size': request.bubble_size
                }

                print(f"📋 Broadcasting updated display settings to {len(welcome_screens)} welcome screens")
                for screen_sid in welcome_screens.keys():
                    await sio.emit('display_settings_updated', updated_settings, to=screen_sid)

            return {
                'success': True,
                'message': 'Display settings updated successfully'
            }
        else:
            return {
                'success': False,
                'message': 'Failed to save display settings'
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Background image endpoints
@app.post("/api/display/upload-background")
async def upload_background_image(file: UploadFile = File(...), admin_id: str = Depends(get_current_admin)):
    """Upload a background image for the welcome screen"""
    try:
        print(f"🔍 Received upload request - file: {file}")
        print(f"📄 File details - filename: {file.filename}, content_type: {file.content_type}")

        # Check if file was provided
        if not file or not file.filename:
            print("❌ No file provided")
            return {
                'success': False,
                'message': 'No file provided'
            }

        # Validate file type
        allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/webp']
        if file.content_type not in allowed_types:
            return {
                'success': False,
                'message': f'Invalid file type. Allowed types: {", ".join(allowed_types)}'
            }

        # Create backgrounds directory if it doesn't exist
        os.makedirs("images/backgrounds", exist_ok=True)

        # Remove any existing background images first
        backgrounds_dir = "images/backgrounds"
        replaced_existing = False
        if os.path.exists(backgrounds_dir):
            for existing_file in os.listdir(backgrounds_dir):
                if existing_file.startswith("welcome_background"):
                    old_file_path = os.path.join(backgrounds_dir, existing_file)
                    os.remove(old_file_path)
                    replaced_existing = True
                    print(f"🗑️ Removed existing background: {old_file_path}")

        # Read and save the file
        contents = await file.read()

        # Save to file system with new file
        file_extension = file.filename.split('.')[-1]
        file_path = f"images/backgrounds/welcome_background.{file_extension}"
        with open(file_path, "wb") as f:
            f.write(contents)

        # Convert to base64 for immediate use (but don't store in config)
        image_base64 = base64.b64encode(contents).decode('utf-8')
        image_data_url = f"data:{file.content_type};base64,{image_base64}"

        # Store only the file path in config
        config_manager.set_display_config(
            use_background_image=True,
            background_image=file_path
        )

        # Broadcast new background image to all connected welcome screens
        if welcome_screens:
            for screen_sid in welcome_screens.keys():
                await sio.emit('background_image_data', {
                    'backgroundImage': image_data_url,
                    'useBackgroundImage': True
                }, to=screen_sid)

        # Add cache buster to force refresh
        import time
        cache_buster = int(time.time() * 1000)

        return {
            'success': True,
            'message': 'Background image replaced successfully' if replaced_existing else 'Background image uploaded successfully',
            'image_url': f'/api/display/background-image?t={cache_buster}'
        }
    except Exception as e:
        print(f"❌ Upload error: {e}")
        print(f"❌ Upload error type: {type(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/display/delete-background")
async def delete_background_image(admin_id: str = Depends(get_current_admin)):
    """Delete the current background image"""
    try:
        # Delete background images
        backgrounds_dir = "images/backgrounds"
        if os.path.exists(backgrounds_dir):
            for file in os.listdir(backgrounds_dir):
                if file.startswith("welcome_background"):
                    os.remove(os.path.join(backgrounds_dir, file))

        # Update config to clear background image settings
        config_manager.set_display_config(
            use_background_image=False,
            background_image=None
        )

        # Broadcast to all connected welcome screens that background was deleted
        if welcome_screens:
            for screen_sid in welcome_screens.keys():
                await sio.emit('background_image_data', {
                    'backgroundImage': None,
                    'useBackgroundImage': False
                }, to=screen_sid)

        return {
            'success': True,
            'message': 'Background image deleted successfully'
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/display/background-image")
async def get_background_image():
    """
    Get the current background image if it exists
    PUBLIC ENDPOINT - No authentication required
    Used by: Welcome screen popup background
    """
    try:
        backgrounds_dir = os.path.join("images", "backgrounds")
        if os.path.exists(backgrounds_dir):
            for file in os.listdir(backgrounds_dir):
                if file.startswith("welcome_background"):
                    file_path = os.path.join(backgrounds_dir, file)
                    # Determine MIME type based on file extension
                    mime_type = "image/jpeg"
                    if file.lower().endswith('.png'):
                        mime_type = "image/png"
                    elif file.lower().endswith('.gif'):
                        mime_type = "image/gif"

                    return FileResponse(
                        file_path,
                        media_type=mime_type,
                        headers={
                            "Cache-Control": "public, max-age=3600",
                            "Access-Control-Allow-Origin": "*"
                        }
                    )

        raise HTTPException(status_code=404, detail="No background image found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# System endpoints
@app.get("/api/system/status")
async def get_system_status(admin_id: str = Depends(get_current_admin)):
    """Get enhanced system status with MediaPipe performance metrics"""
    try:
        people = await get_people(admin_id=admin_id)
        performance_stats = face_recognizer.get_performance_stats()

        return {
            "status": "online",
            "total_people": people.get("total", 0),
            "models_loaded": True,
            "database_connected": True,
            "recognition_system": {
                "detection_method": performance_stats.get("detection_method", "MediaPipe"),
                "recognition_method": performance_stats.get("recognition_method", "OpenCV"),
                "threshold": performance_stats.get("threshold", 0.5),
                "registered_faces": performance_stats.get("registered_faces", 0),
                "avg_detection_time_ms": performance_stats.get("avg_detection_time_ms", 0),
                "avg_recognition_time_ms": performance_stats.get("avg_recognition_time_ms", 0),
                "face_quality_threshold": performance_stats.get("face_quality_threshold", 0.3),
                "cache_enabled": performance_stats.get("cache_enabled", True)
            }
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "models_loaded": False,
            "database_connected": False,
            "recognition_system": {
                "detection_method": "Error",
                "recognition_method": "Error",
                "error": str(e)
            }
        }

@app.get("/api/system/health")
async def health_check():
    """
    Health check endpoint
    PUBLIC ENDPOINT - No authentication required
    Used by: Load balancers, monitoring systems
    """
    return {"status": "healthy", "timestamp": get_current_datetime_other_format()}

@app.get("/api/system/detection-status")
async def get_detection_status(admin_id: str = Depends(get_current_admin)):
    """Get current detection status with session information"""
    active = get_independent_detection_active()
    elapsed = 0
    is_expired = False

    # Get camera configuration
    camera_config = config_manager.get_camera_config()
    camera_source = camera_config.get('source', 'default')
    is_rtsp = camera_source == 'rtsp'

    if active and detection_session_start_time:
        elapsed = int(time.time() - detection_session_start_time)
        is_expired = is_detection_session_expired()

    # For RTSP, allow multiple viewers - should_auto_start is always True
    # For webcam, only allow auto-start if no active session or session is expired
    if is_rtsp:
        should_auto_start = True  # RTSP allows multiple viewers
        should_show_camera = True  # Always allow RTSP viewers
    else:
        should_auto_start = active and (detection_session_owner is None or is_expired)
        should_show_camera = not active or detection_session_owner is None or is_expired

    return {
        "detection_active": active,
        "session_owner": detection_session_owner if active else None,
        "session_elapsed_seconds": elapsed if active else 0,
        "session_expired": is_expired,
        "welcome_screens_connected": len(welcome_screens),
        "admin_clients_connected": len(detection_active),
        "detection_session_id": detection_session_id,
        "should_auto_start": should_auto_start,
        "should_show_camera": should_show_camera,
        "camera_source": camera_source,
        "is_rtsp": is_rtsp,
        "timestamp": get_current_datetime_other_format()
    }

@app.post("/api/system/invalidate-cache")
async def invalidate_face_cache(admin_id: str = Depends(get_current_admin)):
    """Invalidate face encoding cache and rebuild from images"""
    try:
        # Invalidate cache
        face_recognizer.invalidate_cache()

        # Rebuild face dictionary
        face_recognizer.create_features()

        performance_stats = face_recognizer.get_performance_stats()

        return {
            "success": True,
            "message": "Face encoding cache invalidated and rebuilt",
            "registered_faces": performance_stats.get("registered_faces", 0),
            "cache_enabled": performance_stats.get("cache_enabled", True)
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to invalidate cache: {str(e)}"
        }

@app.post("/api/system/cleanup-faiss")
async def cleanup_faiss_database(admin_id: str = Depends(get_current_admin)):
    """
    Clean up orphaned entries in FAISS database.
    Removes entries for people who were deleted before FAISS synchronization was implemented.
    """
    try:
        cleanup_result = face_recognizer.cleanup_orphaned_faces()

        return {
            "success": cleanup_result.get("success", False),
            "message": cleanup_result.get("message", ""),
            "statistics": {
                "orphaned_found": cleanup_result.get("orphaned_count", 0),
                "entries_removed": cleanup_result.get("removed_count", 0),
                "valid_persons": cleanup_result.get("valid_persons", 0),
                "orphaned_ids": cleanup_result.get("orphaned_ids", [])
            }
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to clean up FAISS database: {str(e)}",
            "error": str(e)
        }

@app.get("/api/rtsp/stream-with-overlay")
async def rtsp_stream_with_overlay(request: Request):
    """Stream RTSP video feed with face detection overlays as HTTP MJPEG stream"""
    camera_config = config_manager.get_camera_config()

    if camera_config.get('source') != 'rtsp' or not camera_config.get('rtsp_url'):
        raise HTTPException(status_code=400, detail="RTSP not configured")

    rtsp_url = camera_config['rtsp_url']

    # Automatically start detection if not already active
    if not get_independent_detection_active():
        print(f"🎯 Auto-starting detection for RTSP stream")
        set_independent_detection_active(True, owner_sid="rtsp_stream")
        face_recognizer.start_detection()

    # Create unique stream ID for this request
    stream_id = f"ffmpeg_{id(request)}"
    ffmpeg_streams[stream_id] = True

    print(f"🎬 Starting FFmpeg RTSP stream with overlays {stream_id} from: {rtsp_url}")

    # Create a queue for frame data
    frame_queue = queue.Queue(maxsize=10)
    stop_event = asyncio.Event()

    # Start the background processing thread
    asyncio.create_task(
        process_rtsp_with_ffmpeg_overlay(rtsp_url, frame_queue, stop_event)
    )

    # Wait for first frame to be available (with timeout)
    print(f"⏳ Waiting for first frame from RTSP stream...")
    frame_wait_start = time.time()
    first_frame_timeout = 10  # seconds
    while frame_queue.empty() and (time.time() - frame_wait_start) < first_frame_timeout:
        await asyncio.sleep(0.1)

    if frame_queue.empty():
        stop_event.set()
        if stream_id in ffmpeg_streams:
            del ffmpeg_streams[stream_id]
        print(f"❌ Timeout waiting for first frame from RTSP stream")
        raise HTTPException(status_code=500, detail="RTSP stream failed to produce frames. Check camera connection and URL.")

    print(f"✅ First frame received, starting stream...")

    def generate_frames():
        try:
            while ffmpeg_streams.get(stream_id, False) and get_independent_detection_active():
                try:
                    # Get frame from queue with minimal timeout for responsiveness
                    frame_data = frame_queue.get(timeout=0.1)

                    # Yield frame in multipart format
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')

                except queue.Empty:
                    # If no frame available, continue
                    continue
                except Exception as e:
                    print(f"❌ Error in frame generation: {e}")
                    break

        finally:
            # Cleanup
            stop_event.set()
            if stream_id in ffmpeg_streams:
                del ffmpeg_streams[stream_id]
            print(f"🛑 FFmpeg stream {stream_id} closed")

    return StreamingResponse(
        generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@app.get("/api/webcam/stream-with-overlay")
async def webcam_stream_with_overlay(request: Request):
    """Stream webcam video with face detection overlays - no base64 needed"""

    # Create unique stream ID
    stream_id = f"webcam_{id(request)}"

    # Check if webcam, device, or default is configured
    camera_config = config_manager.get_camera_config()
    source = camera_config.get('source')
    if source not in ['webcam', 'device', 'default']:
        raise HTTPException(status_code=400, detail="Webcam, device, or default not configured as source")

    # Automatically start detection if not already active
    if not get_independent_detection_active():
        print(f"🎯 Auto-starting detection for webcam stream")
        set_independent_detection_active(True, owner_sid="webcam_stream")
        face_recognizer.start_detection()

    # Create queue for frames
    frame_queue = queue.Queue(maxsize=10)

    # Mark stream as active
    webcam_streams[stream_id] = True
    print(f"📹 Starting webcam stream with overlay {stream_id}")

    # Start the background processing thread
    asyncio.create_task(
        process_webcam_with_overlay(frame_queue, stream_id)
    )

    # Wait for first frame to be available (with timeout)
    print(f"⏳ Waiting for first frame from webcam...")
    frame_wait_start = time.time()
    first_frame_timeout = 5  # seconds (shorter for webcam)
    while frame_queue.empty() and (time.time() - frame_wait_start) < first_frame_timeout:
        await asyncio.sleep(0.1)

    if frame_queue.empty():
        if stream_id in webcam_streams:
            del webcam_streams[stream_id]
        print(f"❌ Timeout waiting for first frame from webcam")
        raise HTTPException(status_code=500, detail="Webcam failed to produce frames. Check camera permissions and availability.")

    print(f"✅ First frame received, starting stream...")

    def generate_frames():
        try:
            while webcam_streams.get(stream_id, False) and get_independent_detection_active():
                try:
                    # Get frame from queue with minimal timeout
                    frame_data = frame_queue.get(timeout=0.1)

                    # Yield frame in multipart format
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')

                except queue.Empty:
                    continue
                except Exception as e:
                    print(f"❌ Error in webcam frame generation: {e}")
                    break

        finally:
            # Cleanup
            if stream_id in webcam_streams:
                del webcam_streams[stream_id]
            print(f"🛑 Webcam stream {stream_id} closed")

    return StreamingResponse(
        generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

async def process_webcam_with_overlay(output_queue, stream_id):
    """Process webcam stream with face detection overlays"""
    print(f"🎥 Starting webcam processing with overlays")

    try:
        # Get device_id from config
        camera_config = config_manager.get_camera_config()
        device_id = camera_config.get('device_id')

        # Use device_id if specified, otherwise default to 0
        if device_id:
            try:
                camera_index = int(device_id)  # Try to convert to int for device index
                print(f"📹 Using webcam device index: {camera_index}")
            except ValueError:
                # Try to find a working camera index dynamically
                # Since browser provides device IDs but backend needs indices,
                # we'll try available camera indices until we find one that works
                camera_index = None

                # Test cameras 0-9 to find available ones
                for i in range(10):
                    try:
                        test_cap = cv2.VideoCapture(i, cv2.CAP_AVFOUNDATION)
                        if test_cap.isOpened():
                            ret, _ = test_cap.read()
                            if ret:
                                if camera_index is None:  # Use first available camera as fallback
                                    camera_index = i
                        test_cap.release()
                    except:
                        pass

                if camera_index is None:
                    camera_index = 0  # Fallback to default
                    print(f"⚠️ No cameras found, using default index 0")
                else:
                    print(f"📹 Device {device_id[:12]}... → using available camera index: {camera_index}")
        else:
            camera_index = 0  # Default webcam
            print(f"📹 Using default webcam (index 0)")

        # Initialize capture in thread to avoid blocking
        # Use AVFoundation backend for better macOS compatibility (like original PyQt5)
        loop = asyncio.get_event_loop()
        cap = await loop.run_in_executor(None, cv2.VideoCapture, camera_index, cv2.CAP_AVFOUNDATION)
        await loop.run_in_executor(None, cap.set, cv2.CAP_PROP_BUFFERSIZE, 1)
        await loop.run_in_executor(None, cap.set, cv2.CAP_PROP_FRAME_WIDTH, 640)
        await loop.run_in_executor(None, cap.set, cv2.CAP_PROP_FRAME_HEIGHT, 480)
        await loop.run_in_executor(None, cap.set, cv2.CAP_PROP_FPS, 30)

        if not cap.isOpened():
            print(f"❌ Failed to open webcam")
            return

        # Get video properties
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30

        print(f"📺 Webcam properties: {width}x{height} @ {fps}fps")

        detection_results_cache = []
        frame_count = 0
        consecutive_failures = 0
        max_consecutive_failures = 100  # Exit after 100 consecutive frame read failures

        while webcam_streams.get(stream_id, False) and get_independent_detection_active():
            # Read frame in thread to avoid blocking
            ret, frame = await loop.run_in_executor(None, cap.read)
            if not ret:
                consecutive_failures += 1
                print(f"⚠️ Failed to read frame from webcam (attempt {consecutive_failures}/{max_consecutive_failures})")

                if consecutive_failures >= max_consecutive_failures:
                    print(f"❌ Too many consecutive failures ({consecutive_failures}), stopping webcam stream")
                    break

                await asyncio.sleep(0.1)  # Wait longer between retries
                continue

            # Reset failure counter on successful read
            consecutive_failures = 0
            frame_count += 1

            try:
                # Resize frame to consistent size like original PyQt5 implementation (800x600)
                # This ensures proper bounding box positioning and consistent performance
                display_frame = cv2.resize(frame, (800, 600))

                # Run face detection every frame for webcam (maximum responsiveness)
                # Webcam is typically local and lower resolution, so can handle full FPS detection
                frame_features, faces = face_recognizer.recognize_face(display_frame)

                # Process detection results
                detection_results_cache = []
                if faces is not None and len(faces) > 0:
                   # print(f"🔍 BACKGROUND WEBCAM: Detected {len(faces)} faces in frame {frame_count}")
                    # Calculate scaling factors from display frame (800x600) back to original frame
                    original_height, original_width = frame.shape[:2]
                    scale_x = original_width / 800.0
                    scale_y = original_height / 600.0

                    for i, face_detection in enumerate(faces):
                        x1, y1, w, h = face_detection.bbox
                        x2, y2 = x1 + w, y1 + h

                        # Scale bounding box back to original frame size
                        x1_scaled = int(x1 * scale_x)
                        y1_scaled = int(y1 * scale_y)
                        x2_scaled = int(x2 * scale_x)
                        y2_scaled = int(y2 * scale_y)

                        result = {
                            'bbox': [x1_scaled, y1_scaled, x2_scaled, y2_scaled],
                            'confidence': float(face_detection.confidence),
                            'quality_score': float(face_detection.quality_score),
                            'face_area': int(face_detection.face_area),
                            'is_frontal': bool(face_detection.is_frontal),
                            'recognized': False,
                            'person_name': 'Unknown',
                            'match_confidence': 0.0
                        }

                        # Check for face recognition match
                        if i < len(frame_features) and face_recognizer.dictionary:
                            feature = frame_features[i]
                            best_match = None
                            highest_score = 0

                            dictionary_copy = dict(face_recognizer.dictionary)
                            for person_id, ref_feature in dictionary_copy.items():
                                score = face_recognizer.face_recognizer.match(feature, ref_feature)

                                if score > face_recognizer.threshold and score > highest_score:
                                    highest_score = score
                                    person_name = db.get_person_name(person_id)
                                    person_title = db.get_person_title(person_id)
                                    best_match = {
                                        'person_id': person_id,
                                        'person_name': person_name,
                                        'person_title': person_title,
                                        'confidence': float(score)
                                    }

                            if best_match:
                                result.update({
                                    'person_id': best_match['person_id'],
                                    'person_name': best_match['person_name'],
                                    'match_confidence': best_match['confidence'],
                                    'recognized': True
                                })

                                # Recognition cooldown and broadcasting logic
                                current_time = time.time()
                                person_name = best_match['person_name']

                                # Only broadcast if enough time has passed since last recognition
                                if should_broadcast_recognition(person_name, current_time, recognition_cooldown):
                                    # Create standardized recognition data
                                    recognition_data = create_recognition_data(best_match, current_time)


                                    # Broadcast to welcome screens via SocketIO
                                    await broadcast_recognition_to_welcome_screens(person_name, recognition_data, "WEBCAM")

                        detection_results_cache.append(result)
                else:
                    # No faces detected - reset recognition state to allow immediate re-detection
                    global last_detected_name, last_recognition_time
                    if last_detected_name != "":
                        print(f"🔄 No faces detected - resetting recognition state (was: {last_detected_name})")
                        last_detected_name = ""
                        last_recognition_time = 0.0
                        # Signal SSE clients of recognition change
                        signal_recognition_change()

                # Send detection results to any connected Socket.IO clients for UI updates only if independent detection is active
                if detection_results_cache and get_independent_detection_active():
                    for sid in detection_active.keys():
                        asyncio.create_task(sio.emit('face_detection_result', {
                            "faces": detection_results_cache,
                            "timestamp": time.time(),
                            "frame_size": {"width": frame.shape[1], "height": frame.shape[0]}
                        }, to=sid))

            except Exception as e:
                print(f"❌ Error in webcam face detection: {e}")

            # Draw overlays on frame
            if detection_results_cache:
                frame = draw_detection_overlays_on_frame(frame, detection_results_cache)

            # Encode frame as JPEG
            _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])

            # Put frame in output queue
            if not output_queue.full():
                try:
                    output_queue.put_nowait(buffer.tobytes())
                except queue.Full:
                    pass  # Skip frame if queue is full

            # Frame rate limiting for performance balance (inspired by original PyQt5 timing)
            # Original used 200ms timer (5 FPS), we use 33ms for 30 FPS webcam responsiveness
            await asyncio.sleep(0.033)

        cap.release()
        print("🛑 Webcam processing stopped")

    except Exception as e:
        print(f"❌ Error in webcam stream processing: {e}")
        import traceback
        traceback.print_exc()

        # Ensure camera is released even on exception
        try:
            cap.release()
        except:
            pass

@app.get("/api/webcam/test")
async def test_webcam(admin_id: str = Depends(get_current_admin)):
    """Test webcam connection without streaming"""
    camera_config = config_manager.get_camera_config()

    if camera_config.get('source') not in ['webcam', 'device', 'default']:
        return {"success": False, "error": "Webcam/device not configured as source"}

    print(f"📹 Testing webcam connection")

    try:
        # Use same camera selection logic as other functions
        device_id = camera_config.get('device_id')
        camera_index = 0  # Default

        # Use device_id if specified, otherwise default to 0
        if device_id:
            try:
                camera_index = int(device_id)  # Try to convert to int for device index
                print(f"📹 Testing webcam device index: {camera_index}")
            except ValueError:
                # Try to find a working camera index dynamically
                print(f"📹 Device ID {device_id[:12]}... not numeric, finding available camera")
                for i in range(10):
                    try:
                        test_cap = cv2.VideoCapture(i, cv2.CAP_AVFOUNDATION)
                        if test_cap.isOpened():
                            ret, _ = test_cap.read()
                            if ret:
                                camera_index = i
                                print(f"📹 Found working camera at index: {camera_index}")
                                break
                        test_cap.release()
                    except:
                        pass
        else:
            print(f"📹 Testing default webcam (index 0)")

        cap = cv2.VideoCapture(camera_index, cv2.CAP_AVFOUNDATION)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not cap.isOpened():
            cap.release()
            return {"success": False, "error": "Failed to open webcam"}

        # Try to read one frame
        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            return {"success": False, "error": "Failed to read frame from webcam"}

        height, width = frame.shape[:2]
        return {
            "success": True,
            "message": "Webcam connection successful",
            "frame_size": {"width": int(width), "height": int(height)}
        }

    except Exception as e:
        return {"success": False, "error": f"Webcam test failed: {str(e)}"}

@app.get("/api/rtsp/test")
async def test_rtsp(admin_id: str = Depends(get_current_admin)):
    """Test RTSP connection without streaming"""
    camera_config = config_manager.get_camera_config()

    if camera_config.get('source') != 'rtsp' or not camera_config.get('rtsp_url'):
        return {"success": False, "error": "RTSP not configured"}

    rtsp_url = camera_config['rtsp_url']
    print(f"📡 Testing RTSP connection: {rtsp_url}")

    try:
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not cap.isOpened():
            cap.release()
            return {"success": False, "error": "Failed to open RTSP stream"}

        # Try to read one frame
        ret, frame = cap.read()
        cap.release()

        if not ret or frame is None:
            return {"success": False, "error": "Failed to read frame from RTSP stream"}

        height, width = frame.shape[:2]
        return {
            "success": True,
            "message": "RTSP connection successful",
            "frame_size": {"width": int(width), "height": int(height)},
            "rtsp_url": rtsp_url
        }

    except Exception as e:
        return {"success": False, "error": f"RTSP test failed: {str(e)}"}

@app.post("/api/webcam/stop")
async def stop_webcam_streams(admin_id: str = Depends(get_current_admin)):
    """Stop webcam streams - admin has full control regardless of welcome screen connections"""
    webcam_stream_count = len(webcam_streams)

    # Always stop streams when admin requests it
    webcam_streams.clear()

    # Note: Do NOT automatically set detection_active = False here
    # Detection state should only be controlled by explicit admin actions via socket events
    print(f"🛑 Stopped {webcam_stream_count} webcam streams - detection state controlled separately")

    return {
        "success": True,
        "stopped_webcam_streams": webcam_stream_count,
        "message": "Webcam streams stopped"
    }

@app.post("/api/rtsp/stop")
async def stop_rtsp_streams(admin_id: str = Depends(get_current_admin)):
    """Stop RTSP streams - admin has full control regardless of welcome screen connections"""
    rtsp_stream_count = len(rtsp_streams)
    ffmpeg_stream_count = len(ffmpeg_streams)

    # Always stop streams when admin requests it
    rtsp_streams.clear()
    ffmpeg_streams.clear()
    total_stopped = rtsp_stream_count + ffmpeg_stream_count

    # Note: Do NOT automatically set detection_active = False here
    # Detection state should only be controlled by explicit admin actions via socket events
    print(f"🛑 Stopped {rtsp_stream_count} RTSP streams and {ffmpeg_stream_count} FFmpeg streams - detection state controlled separately")

    return {
        "success": True,
        "stopped_rtsp_streams": rtsp_stream_count,
        "stopped_ffmpeg_streams": ffmpeg_stream_count,
        "total_stopped": total_stopped,
        "message": "RTSP streams stopped"
    }

def cleanup_on_exit():
    """Clean up resources on server shutdown"""
    print("🧹 Cleaning up resources...")

    # Stop all active streams
    rtsp_streams.clear()
    ffmpeg_streams.clear()
    webcam_streams.clear()

    # Clear detection state
    detection_active.clear()
    welcome_screens.clear()

    print("✅ Cleanup complete")

async def start_background_rtsp_for_welcome_screens():
    """Start background RTSP processing specifically for welcome screen recognition"""
    camera_config = config_manager.get_camera_config()
    rtsp_url = camera_config.get('rtsp_url')

    if not rtsp_url:
        print("❌ No RTSP URL configured for background processing")
        return

    stream_id = "welcome_screen_bg_rtsp"
    ffmpeg_streams[stream_id] = True

    print(f"🎬 Starting background RTSP processing for welcome screens: {rtsp_url}")

    # Create a dummy queue since we don't need video output, just recognition events
    dummy_queue = queue.Queue(maxsize=1)  # Small queue since we're not outputting video
    stop_event = asyncio.Event()

    # Use the consolidated auto-retry wrapper
    async def rtsp_process_func():
        await process_rtsp_with_ffmpeg_overlay(rtsp_url, dummy_queue, stop_event)

    await run_with_auto_retry(rtsp_process_func, stream_id, "RTSP")

async def start_background_webcam_for_welcome_screens():
    """Start background webcam processing specifically for welcome screen recognition"""
    stream_id = "welcome_screen_bg_webcam"
    webcam_streams[stream_id] = True

    print(f"📹 Starting background webcam processing for welcome screens")

    # Create a dummy queue since we don't need video output, just recognition events
    dummy_queue = queue.Queue(maxsize=1)  # Small queue since we're not outputting video

    # Use the consolidated auto-retry wrapper
    async def webcam_process_func():
        await process_webcam_with_overlay(dummy_queue, stream_id)

    await run_with_auto_retry(webcam_process_func, stream_id, "WEBCAM")

def signal_handler(signum, _):
    """Handle shutdown signals gracefully"""
    print(f"\n🛑 Received signal {signum}, shutting down gracefully...")
    cleanup_on_exit()
    import sys
    sys.exit(0)

if __name__ == "__main__":
    import signal
    import atexit

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Kill command

    # Register cleanup function to run on normal exit
    atexit.register(cleanup_on_exit)

    print("🚀 Face Recognition API starting...")
    print("📊 Database initialized")
    print("🤖 AI models loaded")
    print("📷 Camera system ready")

    # Run FAISS cleanup on startup to remove orphaned entries
    print("🧹 Checking for orphaned FAISS entries...")
    cleanup_result = face_recognizer.cleanup_orphaned_faces()
    if cleanup_result.get("orphaned_count", 0) > 0:
        print(f"✅ Cleaned up {cleanup_result.get('removed_count', 0)} orphaned face entries")
    else:
        print("✅ FAISS database is clean")
    print("✅ API ready at http://localhost:8000/api")
    print("📚 API docs available at http://localhost:8000/api/docs")

    try:
        # Run the server with SocketIO
        # Note: reload should be False in production to avoid duplicate initialization
        reload_enabled = os.getenv('UVICORN_RELOAD', 'false').lower() in ('true', '1', 'yes')
        uvicorn.run(
            "api:socket_app",  # Use the SocketIO app instead of FastAPI app directly
            host="0.0.0.0",
            port=8000,
            reload=reload_enabled,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n🛑 Server interrupted by user")
        cleanup_on_exit()
    except Exception as e:
        print(f"❌ Server error: {e}")
        cleanup_on_exit()