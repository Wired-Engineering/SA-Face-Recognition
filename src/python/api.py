from fastapi import FastAPI, HTTPException, File, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import uvicorn
import base64
import cv2
import numpy as np
from PIL import Image
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

# SocketIO imports
import socketio

from DatabaseManager import MySqlite3Manager
from utils import get_current_datetime_other_format
from MediaPipe_Face_recognizer import MediaPipeFaceRecognizer as FaceRecognizer
from config_manager import config_manager

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

    # Load persistent detection state
    if get_independent_detection_active():
        print(f"🔄 Restored detection state: active (persistent from config)")
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

# Mount SocketIO app
socket_app = socketio.ASGIApp(sio, app)

# Initialize components
db = MySqlite3Manager()
# Initialize MediaPipe face recognizer with default settings
face_recognizer = FaceRecognizer(
    thresold=0.5,  # Default threshold for MediaPipe
    draw=True      # Enable drawing overlays
)

# Thread pool for parallel processing
thread_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="rtsp_worker")

# SocketIO globals
detection_active: Dict[str, bool] = {}
welcome_screens: Dict[str, bool] = {}  # Track welcome screen connections
latest_recognition: Dict = {}  # Store latest recognition result
rtsp_streams: Dict[str, bool] = {}  # Track active RTSP streams
ffmpeg_streams: Dict[str, bool] = {}  # Track active ffmpeg streams with overlays
webcam_streams: Dict[str, bool] = {}  # Track active webcam streams

# Independent detection system - load state from config on startup
detection_session_id = None  # Track the current detection session

def get_independent_detection_active():
    """Get detection state from persistent config"""
    return config_manager.is_detection_active()

def set_independent_detection_active(active: bool):
    """Set detection state and persist to config"""
    return config_manager.set_detection_active(active)

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
        print(f"🎯 Broadcasting recognition for {person_name} (time since last: {time_since_last:.1f}s)")
    else:
        print(f"🔄 Skipping recognition for {person_name} (cooldown: {time_since_last:.1f}s < {cooldown}s)")

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

# Configure logging
logging.basicConfig(level=logging.INFO)

# SocketIO event handlers for WebRTC signaling
@sio.event
async def connect(sid, environ):
    print(f"🔌 Client connected: {sid}")

@sio.event
async def disconnect(sid):
    global detection_session_id

    print(f"🔌 Client disconnected: {sid}")
    # Cleanup detection state for this client
    if sid in detection_active:
        del detection_active[sid]
    # Cleanup welcome screen state
    if sid in welcome_screens:
        del welcome_screens[sid]

    # Detection state is controlled by persistent config and explicit admin actions only
    # Client disconnections should NOT automatically stop detection
    print(f"🔄 Client disconnected - detection state remains unchanged (controlled by admin only)")

@sio.event
async def start_detection(sid, data):
    """Start face detection for a client"""
    global detection_session_id

    print(f"🔍 Starting face detection for client {sid}")
    detection_active[sid] = True

    # Start independent detection if not already active
    if not get_independent_detection_active():
        set_independent_detection_active(True)
        detection_session_id = f"session_{int(time.time())}"
        print(f"🎯 Starting independent detection session: {detection_session_id}")

        # Reset recognition cooldown when starting new detection session
        global last_detected_name, last_recognition_time
        last_detected_name = ""
        last_recognition_time = 0.0
        print(f"🔄 Reset recognition cooldown for new detection session")

        # Start background stream processing for recognition if camera is configured
        camera_config = config_manager.get_camera_config()
        print(f"🔍 Camera config: source={camera_config.get('source')}, rtsp_url={camera_config.get('rtsp_url')}")

        await start_background_processing_for_camera_type()

    await sio.emit('detection_started', {'status': 'started'}, to=sid)


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

    print(f"🛑 Stopping face detection for client {sid} (admin_stop: {is_admin_stop})")
    was_admin_client = sid in detection_active
    if was_admin_client:
        del detection_active[sid]

    # Only stop independent detection if explicitly requested by admin
    # OR if no welcome screens AND no admin clients are connected AND not a page refresh
    if is_admin_stop:
        set_independent_detection_active(False)
        detection_session_id = None
        print(f"🛑 Admin explicitly stopped detection - setting detection.active = false")

        # Stop ALL streams when admin explicitly stops detection (not just background)
        rtsp_stream_count = len(rtsp_streams)
        ffmpeg_stream_count = len(ffmpeg_streams)
        webcam_stream_count = len(webcam_streams)

        rtsp_streams.clear()
        ffmpeg_streams.clear()
        webcam_streams.clear()

        total_stopped = rtsp_stream_count + ffmpeg_stream_count + webcam_stream_count
        print(f"🛑 Admin stop: Cleared {rtsp_stream_count} RTSP, {ffmpeg_stream_count} FFmpeg, {webcam_stream_count} webcam streams (total: {total_stopped})")

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
            'font_size': display_config.get('font_size', 'medium')
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

        # Process detection results
        detection_results = []
        if faces is not None and len(faces) > 0:
            for i, face_detection in enumerate(faces):
                # Get bounding box from FaceDetection object
                x1, y1, w, h = face_detection.bbox
                x2, y2 = x1 + w, y1 + h

                result = {
                    'bbox': [int(x1), int(y1), int(x2), int(y2)],
                    'confidence': float(face_detection.confidence),
                    'quality_score': float(face_detection.quality_score),
                    'face_area': int(face_detection.face_area),
                    'is_frontal': bool(face_detection.is_frontal)
                }

                # Include 468 landmark points if enabled (for visualization/debugging)
                if face_recognizer.include_landmarks and face_detection.landmarks is not None:
                    # Convert landmarks to list format for JSON serialization
                    # Each landmark is [x, y, z] where x,y are normalized coordinates (0-1)
                    landmarks_list = face_detection.landmarks.tolist()
                    result['landmarks'] = landmarks_list
                    result['landmark_count'] = len(landmarks_list)

                # Check for face recognition match using ensemble voting
                if i < len(frame_features) and face_recognizer.dictionary:
                    feature = frame_features[i]

                    # Use ensemble matching if available, otherwise fall back to standard matching
                    try:
                        # Get landmarks for context-aware matching
                        landmarks = face_detection.landmarks if hasattr(face_detection, 'landmarks') else None

                        # Try ensemble matching first
                        match_result, (person_id, score) = face_recognizer.ensemble_match(feature, landmarks)

                        if match_result:
                            # Extract base person ID (remove template suffix if present)
                            base_person_id = person_id.split('%')[0] if '%' in person_id else person_id

                            person_name = db.get_person_name(base_person_id)
                            person_title = db.get_person_title(base_person_id)

                            best_match = {
                                'person_id': base_person_id,
                                'person_name': person_name,
                                'person_title': person_title,
                                'confidence': float(score)
                            }
                        else:
                            best_match = None

                    except Exception as e:
                        print(f"❌ Ensemble matching error, falling back to standard matching: {e}")
                        # Fallback to original matching logic
                        best_match = None
                        highest_score = 0

                        for person_id, ref_feature in face_recognizer.dictionary.items():
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

                        # Store latest recognition for polling endpoints
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
                        latest_recognition.update(recognition_data)

                        # Broadcast recognition to all welcome screens
                        for welcome_screen_sid in welcome_screens.keys():
                            await sio.emit('recognition_result', recognition_data, to=welcome_screen_sid)

                    else:
                        result.update({
                            'person_id': 'UNKNOWN',
                            'person_name': 'Unknown Person',
                            'match_confidence': 0.0,
                            'recognized': False
                        })

                detection_results.append(result)

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
    """Configure OpenCV to use hardware acceleration when available (CPU-first approach)"""
    import os

    # Default to CPU-only for production stability
    # GPU acceleration must be explicitly enabled
    enable_gpu = os.getenv('ENABLE_GPU_ACCELERATION', '').lower() in ('true', '1', 'yes')

    # If GPU acceleration not explicitly enabled, use CPU
    if not enable_gpu:
        print("💻 Using CPU-only processing (default for production stability)")
        print("💡 To enable GPU acceleration: set ENABLE_GPU_ACCELERATION=true")
        return "cpu"

    # GPU acceleration explicitly requested - proceed with detection
    print("🚀 GPU acceleration explicitly enabled - detecting hardware...")

    # Check if running in Docker container
    is_docker = os.path.exists('/.dockerenv') or os.path.exists('/proc/1/cgroup')
    if is_docker:
        print("🐳 Running in Docker container - checking for GPU passthrough...")

    try:
        # Check for CUDA support
        if cv2.cuda.getCudaEnabledDeviceCount() > 0:
            print("🚀 CUDA GPU acceleration available")
            return "cuda"
    except:
        pass

    try:
        # Check for Intel Quick Sync Video (QSV) / iGPU support
        backends = cv2.videoio_registry.getBackends()
        if cv2.CAP_INTEL_MFX in backends:
            # Verify Intel GPU device accessibility in container
            intel_devices = ['/dev/dri/renderD128', '/dev/dri/card0']
            if any(os.path.exists(device) for device in intel_devices):
                print("🚀 Intel QuickSync Video (QSV) acceleration available with device passthrough")
                print("📱 Using Intel Media SDK (MFX) backend for hardware acceleration")
                return "intel_mfx"
            else:
                print("⚠️ Intel MFX/QuickSync backend available but no GPU devices found")
                print("💡 Ensure DRI devices are mapped: --device=/dev/dri:/dev/dri")
    except:
        pass

    try:
        # Check for VAAPI (Video Acceleration API) - Linux hardware acceleration
        if os.path.exists('/dev/dri'):
            # Check if we can access DRI devices
            dri_devices = os.listdir('/dev/dri')
            if dri_devices:
                print(f"🚀 VAAPI hardware acceleration available (devices: {dri_devices})")
                # Try to use FFMPEG with hardware acceleration
                return "vaapi"
    except:
        pass

    try:
        # Check for DirectShow with hardware acceleration on Windows
        if cv2.CAP_DSHOW in cv2.videoio_registry.getBackends():
            print("🚀 DirectShow hardware acceleration available")
            return "dshow"
    except:
        pass

    if is_docker:
        print("❌ No GPU passthrough detected in Docker container")
        print("💡 To enable GPU acceleration:")
        print("   Intel: --device=/dev/dri:/dev/dri --group-add video")
        print("   AMD:   --device=/dev/dri:/dev/dri --device=/dev/kfd:/dev/kfd --group-add video --group-add render")
        print("   NVIDIA: --gpus all (requires nvidia-docker)")

    print("ℹ️ Using CPU-only processing (no hardware acceleration detected)")
    return "cpu"


def create_optimized_capture(rtsp_url, hw_backend="cpu"):
    """Create an optimized VideoCapture with hardware acceleration (Docker-compatible)"""
    cap = None

    if hw_backend == "cuda":
        # Try CUDA-accelerated capture
        try:
            cap = cv2.VideoCapture(rtsp_url, cv2.CAP_GSTREAMER)
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('H', '2', '6', '4'))
        except:
            pass

    elif hw_backend == "intel_mfx":
        # Try Intel Quick Sync Video (QSV) with Media SDK
        try:
            print(f"🔧 Initializing Intel QuickSync capture for: {rtsp_url}")
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
        # Try VAAPI hardware acceleration (Linux containers)
        try:
            # Use GStreamer with VAAPI
            gst_pipeline = f'rtspsrc location={rtsp_url} ! rtph264depay ! h264parse ! vaapih264dec ! videoconvert ! appsink'
            cap = cv2.VideoCapture(gst_pipeline, cv2.CAP_GSTREAMER)
        except:
            # Fallback to regular FFMPEG with potential hardware acceleration
            cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)

    elif hw_backend == "dshow":
        # Try DirectShow with hardware acceleration
        try:
            cap = cv2.VideoCapture(rtsp_url, cv2.CAP_DSHOW)
        except:
            pass

    # Fallback to FFmpeg if hardware acceleration fails
    if cap is None or not cap.isOpened():
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)

    # Optimize capture settings
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Reduce buffer to minimize latency
        cap.set(cv2.CAP_PROP_FPS, 30)  # Target 30 FPS
        # Enable hardware decoding if available
        try:
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc('H', '2', '6', '4'))
        except:
            pass  # Ignore if codec setting fails

    return cap


def process_frame_threaded(frame_data):
    """Process a frame in a separate thread for face detection"""
    frame, frame_count = frame_data

    try:
        # Resize frame to consistent size like original implementation (800x600)
        display_frame = cv2.resize(frame, (800, 600))
        frame_features, faces = face_recognizer.recognize_face(display_frame)

        detection_results = []
        if faces is not None and len(faces) > 0:
            # Calculate scaling factors from display frame back to original frame
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
                    'match_confidence': 0.0,
                    'frame_count': frame_count
                }

                # Check for face recognition match
                if i < len(frame_features) and face_recognizer.dictionary:
                    feature = frame_features[i]
                    best_match = None
                    highest_score = 0

                    for person_id, ref_feature in face_recognizer.dictionary.items():
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

                detection_results.append(result)

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

        frame_count = 0
        detection_results_cache = []
        pending_futures = {}  # Track pending detection tasks

        # Keep detection running as long as it's marked active
        while not stop_event.is_set() and get_independent_detection_active():
            # Read frame in thread to avoid blocking
            ret, frame = await loop.run_in_executor(None, cap.read)
            if not ret:
                print("⚠️ Failed to read frame from RTSP stream")
                await asyncio.sleep(0.01)  # Reduced delay
                continue

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

                                    # Store latest recognition
                                    latest_recognition.update(recognition_data)

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

class MediaPipeSettings(BaseModel):
    detection_confidence: Optional[float] = 0.5
    tracking_confidence: Optional[float] = 0.7  # Higher default for video tracking
    max_faces: Optional[int] = 20
    refine_landmarks: Optional[bool] = True
    unlimited_faces: Optional[bool] = False
    include_landmarks: Optional[bool] = False  # Include 468 landmarks in API response

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
async def change_admin_password(request: AdminPasswordChange):
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
async def get_people():
    """Get all registered people with complete information"""
    try:
        person_ids = db.get_all_person_ids()
        people = []

        for person_id in person_ids:
            person_name = db.get_person_name(person_id)
            person_title = db.get_person_title(person_id)
            person_registration = db.get_person_registration(person_id)
            if person_name:
                # Check if reference image exists
                image_path = f'images/{person_id}.png'
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
                        if filename.startswith(f'{person_id}.png') or filename.startswith(f'{person_id}%'):
                            photo_files.append(filename)
                            if filename != f'{person_id}.png':
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
            'total': len(people)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/people/register")
async def register_person(request: personRegistration):
    """Register a new person with auto-generated UUID"""
    try:
        # Generate a unique UUID for the person
        person_id = str(uuid.uuid4())

        # Decode base64 image
        if request.image_data.startswith('data:image'):
            image_data = request.image_data.split(',')[1]
        else:
            image_data = request.image_data

        image_bytes = base64.b64decode(image_data)
        image = Image.open(BytesIO(image_bytes))

        # Convert to OpenCV format
        image_cv = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

        # Use the face recognizer to detect faces
        _, faces = face_recognizer.recognize_face(image_cv, f"{person_id}.png")

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

        # Save person to database (UUID ensures uniqueness, so no conflict possible)
        db_result = db.insert_into_person(person_id, request.person_name, request.person_title, request.person_registration)

        if 'already exist' in db_result:
            # This should theoretically never happen with UUID, but handle it just in case
            return {
                'success': False,
                'message': 'Unexpected ID collision occurred, please try again'
            }

        # Save face image
        os.makedirs('images', exist_ok=True)
        image_path = f'images/{person_id}.png'
        cv2.imwrite(image_path, image_cv)

        # Recreate features dictionary with new person
        face_recognizer.create_features()

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

@app.post("/api/people/{person_id}/add-photo")
async def add_additional_photo(person_id: str, request: AdditionalPhotoUpload):
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

        # Convert to OpenCV format
        image_cv = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

        # Use the face recognizer to detect faces
        _, faces = face_recognizer.recognize_face(image_cv, f"{person_id}_temp.png")

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

        # Generate simple identifier for additional photos
        existing_photos = [f for f in os.listdir('images') if f.startswith(f'{person_id}%') or f == f'{person_id}.png']
        photo_number = len(existing_photos)

        # Save additional photo with simple numbering
        os.makedirs('images', exist_ok=True)
        image_filename = f'{person_id}%{photo_number}.png'
        image_path = f'images/{image_filename}'
        cv2.imwrite(image_path, image_cv)

        # Recreate features dictionary to include new photo
        face_recognizer.create_features()

        return {
            'success': True,
            'message': 'Additional photo added successfully',
            'person_id': person_id,
            'total_photos': photo_number + 1
        }

    except Exception as e:
        return {
            'success': False,
            'message': f'Failed to add additional photo: {str(e)}'
        }

@app.delete("/api/people/{person_id}")
async def delete_person(person_id: str):
    """Delete a person and all their photos"""
    try:
        # Delete from database first
        result = db.delete_data_from_person(person_id)
        if result:
            # Delete all photo files for this person
            deleted_photos = []
            if os.path.exists('images'):
                for filename in os.listdir('images'):
                    if filename.startswith(f'{person_id}.png') or filename.startswith(f'{person_id}%'):
                        file_path = os.path.join('images', filename)
                        try:
                            os.remove(file_path)
                            deleted_photos.append(filename)
                        except Exception as e:
                            print(f"Error deleting photo {filename}: {e}")

            # Recreate features dictionary after deletion
            face_recognizer.create_features()

            message = f'Person deleted successfully'
            if deleted_photos:
                message += f' (removed {len(deleted_photos)} photos)'

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
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/people")
async def delete_all_people():
    """Delete all people from the database"""
    try:
        person_ids = db.get_all_person_ids()
        deleted_count = 0
        failed_deletions = []

        for person_id in person_ids:
            result = db.delete_data_from_person(person_id)
            if result:
                deleted_count += 1
            else:
                failed_deletions.append(person_id)

        # Recreate features dictionary after deletion
        face_recognizer.create_features()

        if len(failed_deletions) == 0:
            return {
                'success': True,
                'message': f'All {deleted_count} people deleted successfully',
                'deleted_count': deleted_count
            }
        else:
            return {
                'success': False,
                'message': f'Deleted {deleted_count} people, but failed to delete {len(failed_deletions)} people',
                'deleted_count': deleted_count,
                'failed_deletions': failed_deletions
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/people/{person_id}/image")
async def get_person_image(person_id: str):
    """Get a person's reference image"""
    try:
        image_path = f'images/{person_id}.png'
        if os.path.exists(image_path):
            # Get file modification time for cache busting
            file_mtime = os.path.getmtime(image_path)
            etag = f'"{person_id}-{int(file_mtime)}"'

            return FileResponse(
                image_path,
                media_type="image/png",
                headers={
                    "Cache-Control": "no-cache, must-revalidate",
                    "Access-Control-Allow-Origin": "*",
                    "ETag": etag,
                    "Last-Modified": time.strftime('%a, %d %b %Y %H:%M:%S GMT', time.gmtime(file_mtime))
                }
            )
        else:
            raise HTTPException(status_code=404, detail="Person image not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Face recognition endpoints
@app.post("/api/recognition/detect")
async def detect_faces(request: FaceDetectionRequest):
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
                    for person_id, ref_feature in face_recognizer.dictionary.items():
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

@app.get("/api/recognition/latest")
async def get_latest_recognition():
    """Get the latest face recognition result for welcome screens"""
    try:
        if latest_recognition:
            return {
                'success': True,
                **latest_recognition
            }
        else:
            return {
                'success': True,
                'user': None,
                'timestamp': None
            }
    except Exception as e:
        return {
            'success': False,
            'message': f'Failed to get latest recognition: {str(e)}',
            'user': None,
            'timestamp': None
        }

# Camera management endpoints
@app.get("/api/camera/settings")
async def get_camera_settings():
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
async def update_camera_settings(request: CameraSettings):
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

# MediaPipe configuration endpoints
@app.get("/api/mediapipe/settings")
async def get_mediapipe_settings():
    """Get current MediaPipe settings"""
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
async def update_mediapipe_settings(request: MediaPipeSettings):
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
async def get_mediapipe_presets():
    """Get predefined MediaPipe configuration presets"""
    try:
        presets = {
            'few_people': {
                'name': '👥 Less than 5 People',
                'description': 'Optimized for small groups, high accuracy and quality',
                'settings': {
                    'detection_confidence': 0.6,
                    'tracking_confidence': 0.7,  # Higher for video tracking
                    'max_faces': 5,
                    'refine_landmarks': True,  # High-quality landmarks
                    'unlimited_faces': False
                }
            },
            'many_people': {
                'name': '👥👥 5+ People (Groups)',
                'description': 'Optimized for larger groups, balanced performance',
                'settings': {
                    'detection_confidence': 0.5,
                    'tracking_confidence': 0.6,  # Balanced for groups
                    'max_faces': 20,
                    'refine_landmarks': True,  # Keep high-quality landmarks
                    'unlimited_faces': False
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
async def apply_mediapipe_preset(request: dict):
    """Apply a predefined MediaPipe configuration preset"""
    try:
        preset_name = request.get('preset')
        presets_response = await get_mediapipe_presets()
        presets = presets_response['presets']

        if preset_name not in presets:
            return {
                'success': False,
                'message': f'Preset "{preset_name}" not found'
            }

        preset_settings = presets[preset_name]['settings']

        # Apply preset to config
        success = config_manager.set_mediapipe_config(**preset_settings)

        if success:
            # Apply to face recognizer
            face_recognizer.configure_mediapipe(**preset_settings)

            return {
                'success': True,
                'message': f'Applied preset: {presets[preset_name]["name"]}',
                'applied_settings': preset_settings
            }
        else:
            return {
                'success': False,
                'message': 'Failed to apply preset'
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/camera/devices")
async def get_camera_devices():
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
async def test_camera(request: CameraSettings):
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
    """Get current display settings"""
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
            'font_size': display_config.get('font_size', 'medium')
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/display/settings")
async def update_display_settings(request: DisplaySettings):
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
            font_size=request.font_size
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
                    'font_size': request.font_size
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
async def upload_background_image(file: UploadFile = File(...)):
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
async def delete_background_image():
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
    """Get the current background image if it exists"""
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
async def get_system_status():
    """Get enhanced system status with MediaPipe performance metrics"""
    try:
        people = await get_people()
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
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": get_current_datetime_other_format()}

@app.get("/api/system/detection-status")
async def get_detection_status():
    """Get current detection status"""
    return {
        "detection_active": get_independent_detection_active(),
        "welcome_screens_connected": len(welcome_screens),
        "admin_clients_connected": len(detection_active),
        "detection_session_id": detection_session_id,
        "should_auto_start": get_independent_detection_active(),  # Frontend should auto-start if backend is active
        "timestamp": get_current_datetime_other_format()
    }

@app.post("/api/system/invalidate-cache")
async def invalidate_face_cache():
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

@app.post("/api/test/trigger-recognition")
async def trigger_test_recognition():
    """Test endpoint to manually trigger a recognition event"""
    print(f"🧪 Manual recognition test triggered")
    print(f"📺 Connected welcome screens: {list(welcome_screens.keys())}")

    if not welcome_screens:
        return {
            "success": False,
            "message": "No welcome screens connected"
        }

    # Create test recognition data using consolidated function
    test_best_match = {
        'person_id': 'TEST_ID',
        'person_name': 'Test User',
        'person_title': 'Test Title',
        'confidence': 0.95
    }

    test_recognition_data = create_recognition_data(test_best_match, time.time())

    # Broadcast to all welcome screens using consolidated function
    await broadcast_recognition_to_welcome_screens("Test User", test_recognition_data, "TEST")

    return {
        "success": True,
        "message": f"Test recognition sent to {len(welcome_screens)} welcome screens",
        "welcome_screens": list(welcome_screens.keys()),
        "test_data": test_recognition_data
    }

@app.get("/api/rtsp/stream-with-overlay")
async def rtsp_stream_with_overlay(request: Request):
    """Stream RTSP video feed with face detection overlays as HTTP MJPEG stream"""
    camera_config = config_manager.get_camera_config()

    if camera_config.get('source') != 'rtsp' or not camera_config.get('rtsp_url'):
        raise HTTPException(status_code=400, detail="RTSP not configured")

    rtsp_url = camera_config['rtsp_url']

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

    def generate_frames():
        try:
            while ffmpeg_streams.get(stream_id, False) and get_independent_detection_active():
                try:
                    # Get frame from queue with minimal timeout for responsiveness
                    frame_data = frame_queue.get(timeout=0.01)

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

    # Create queue for frames
    frame_queue = queue.Queue(maxsize=10)

    # Mark stream as active
    webcam_streams[stream_id] = True
    print(f"📹 Starting webcam stream with overlay {stream_id}")

    # Start the background processing thread
    asyncio.create_task(
        process_webcam_with_overlay(frame_queue, stream_id)
    )

    def generate_frames():
        try:
            while webcam_streams.get(stream_id, False) and get_independent_detection_active():
                try:
                    # Get frame from queue with minimal timeout
                    frame_data = frame_queue.get(timeout=0.01)

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

        while webcam_streams.get(stream_id, False) and get_independent_detection_active():
            # Read frame in thread to avoid blocking
            ret, frame = await loop.run_in_executor(None, cap.read)
            if not ret:
                # Only sleep on failure
                await asyncio.sleep(0.01)
                continue

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

                            for person_id, ref_feature in face_recognizer.dictionary.items():
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

                                    # Store latest recognition
                                    latest_recognition.update(recognition_data)

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
async def test_webcam():
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
async def test_rtsp():
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
async def stop_webcam_streams():
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
async def stop_rtsp_streams():
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
    print("✅ API ready at http://localhost:8000/api")
    print("📚 API docs available at http://localhost:8000/api/docs")

    try:
        # Run the server with SocketIO
        uvicorn.run(
            "api:socket_app",  # Use the SocketIO app instead of FastAPI app directly
            host="0.0.0.0",
            port=8000,
            reload=True,
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n🛑 Server interrupted by user")
        cleanup_on_exit()
    except Exception as e:
        print(f"❌ Server error: {e}")
        cleanup_on_exit()