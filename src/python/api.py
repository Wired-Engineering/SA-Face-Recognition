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
import ffmpeg
import threading
import queue

# SocketIO imports
import socketio

from DatabaseManager import MySqlite3Manager
from utils import get_current_datetime_other_format
from My_Face_recognizer import FaceRecognizer
from config_manager import config_manager

# Lifespan manager for startup and shutdown
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("🚀 Face Recognition API starting...")
    print("📊 Database initialized")
    print("🤖 AI models loaded")
    print("📷 Camera system ready")
    print("✅ API ready at http://localhost:8000")
    print("📚 API docs available at http://localhost:8000/docs")

    # Ensure required directories exist
    os.makedirs("images", exist_ok=True)
    os.makedirs("system", exist_ok=True)

    yield

    # Shutdown - Cleanup SocketIO connections
    print("🔌 Cleaning up SocketIO connections...")
    detection_active.clear()
    print("✅ Cleanup complete")

# Create SocketIO server
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins=["http://localhost:3000", "http://localhost:5173", "http://localhost:5174"]
)

app = FastAPI(
    title="Signature Aviation Face Recognition API",
    description="Face recognition system for person attendance",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://localhost:5174"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount SocketIO app
socket_app = socketio.ASGIApp(sio, app)

# Initialize components
db = MySqlite3Manager()
# Load recognition settings from config
recognition_config = config_manager.get_recognition_config()
face_recognizer = FaceRecognizer(
    thresold=recognition_config.get('threshold', 0.5),
    draw=recognition_config.get('draw_boxes', True)
)

# SocketIO globals
detection_active: Dict[str, bool] = {}
welcome_screens: Dict[str, bool] = {}  # Track welcome screen connections
latest_recognition: Dict = {}  # Store latest recognition result
rtsp_streams: Dict[str, bool] = {}  # Track active RTSP streams
ffmpeg_streams: Dict[str, bool] = {}  # Track active ffmpeg streams with overlays

# Configure logging
logging.basicConfig(level=logging.INFO)

# SocketIO event handlers for WebRTC signaling
@sio.event
async def connect(sid, environ):
    print(f"🔌 Client connected: {sid}")

@sio.event
async def disconnect(sid):
    print(f"🔌 Client disconnected: {sid}")
    # Cleanup detection state for this client
    if sid in detection_active:
        del detection_active[sid]
    # Cleanup welcome screen state
    if sid in welcome_screens:
        del welcome_screens[sid]
    # Stop any RTSP and FFmpeg streams when clients disconnect
    if rtsp_streams or ffmpeg_streams:
        rtsp_count = len(rtsp_streams)
        ffmpeg_count = len(ffmpeg_streams)
        print(f"🛑 Stopping {rtsp_count} RTSP streams and {ffmpeg_count} FFmpeg streams due to client disconnect")
        rtsp_streams.clear()
        ffmpeg_streams.clear()

@sio.event
async def start_detection(sid, data):
    """Start face detection for a client"""
    print(f"🔍 Starting face detection for client {sid}")
    detection_active[sid] = True

    # Check if RTSP is configured - note: RTSP detection is now handled by ffmpeg overlay stream
    camera_config = config_manager.get_camera_config()
    if camera_config.get('source') == 'rtsp' and camera_config.get('rtsp_url'):
        print(f"📡 RTSP detected - detection will be handled by ffmpeg overlay stream, not SocketIO")
        # Don't start the old RTSP processing since overlays are handled by /api/rtsp/stream-with-overlay

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
    print(f"🛑 Stopping face detection for client {sid}")
    detection_active[sid] = False
    await sio.emit('detection_stopped', {'status': 'stopped'}, to=sid)

@sio.event
async def register_welcome_screen(sid, data):
    """Register a welcome screen popup"""
    print(f"📺 Welcome screen registered: {sid}")
    welcome_screens[sid] = True
    await sio.emit('welcome_screen_registered', {'status': 'registered'}, to=sid)

@sio.event
async def unregister_welcome_screen(sid, data):
    """Unregister a welcome screen popup"""
    print(f"📺 Welcome screen unregistered: {sid}")
    if sid in welcome_screens:
        del welcome_screens[sid]
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
async def process_frame(sid, data):
    """Process a single video frame for face detection"""
    try:
        # Check if detection is active for this client
        if not detection_active.get(sid, False):
            return

        # Decode base64 image
        image_data = data['frame']
        if image_data.startswith('data:image'):
            image_data = image_data.split(',')[1]

        image_bytes = base64.b64decode(image_data)
        image = Image.open(BytesIO(image_bytes))
        cv_frame = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

        # Run face detection
        frame_features, faces = face_recognizer.recognize_face(cv_frame)

        # Process detection results
        detection_results = []
        if faces is not None and len(faces) > 0:
            for i, face in enumerate(faces):
                # Get bounding box and convert to regular Python ints
                x1, y1, w, h = face[:4].astype(int)
                x2, y2 = x1 + w, y1 + h

                result = {
                    'bbox': [int(x1), int(y1), int(x2), int(y2)],
                    'confidence': float(face[14]) if len(face) > 14 else 0.0
                }

                # Check for face recognition match
                if i < len(frame_features) and face_recognizer.dictionary:
                    feature = frame_features[i]
                    best_match = None
                    highest_score = 0

                    for person_id, ref_feature in face_recognizer.dictionary.items():
                        score = face_recognizer.face_recognizer.match(feature, ref_feature)
                        if score > face_recognizer.thresold and score > highest_score:
                            highest_score = score
                            person_name = db.get_person_name(person_id)
                            best_match = {
                                'person_id': person_id,
                                'person_name': person_name,
                                'confidence': float(score)
                            }

                    if best_match:
                        result.update({
                            'person_id': best_match['person_id'],
                            'person_name': best_match['person_name'],
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
                                'confidence': best_match['confidence'],
                                'photo': None  # Could add photo path here if needed
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

        # Send detection results with coordinates for frontend overlay rendering
        await sio.emit('face_detection_result', {
            "faces": detection_results,
            "timestamp": time.time(),
            "frame_size": {"width": cv_frame.shape[1], "height": cv_frame.shape[0]}
        }, to=sid)

        if len(detection_results) > 0:
            print(f"🔍 Sent {len(detection_results)} detection results to {sid}")

    except Exception as e:
        print(f"❌ Error processing frame for {sid}: {e}")
        await sio.emit('detection_error', {"error": str(e)}, to=sid)


async def process_rtsp_with_detection(sid, rtsp_url):
    """Process RTSP stream with face detection - no frontend frame processing needed"""
    import asyncio

    print(f"📡 Starting RTSP detection processing for {sid}: {rtsp_url}")

    try:
        cap = cv2.VideoCapture(rtsp_url)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not cap.isOpened():
            print(f"❌ Failed to open RTSP stream: {rtsp_url}")
            await sio.emit('detection_error', {"error": f"Failed to connect to RTSP stream: {rtsp_url}"}, to=sid)
            return

        print(f"✅ RTSP detection stream opened successfully: {rtsp_url}")
        frame_count = 0

        while detection_active.get(sid, False):
            ret, frame = cap.read()
            if not ret:
                print(f"⚠️ Failed to read frame from RTSP detection stream")
                await asyncio.sleep(0.01)  # Reduced delay from 100ms to 10ms
                continue

            frame_count += 1

            try:
                # Run face detection on backend
                frame_features, faces = face_recognizer.recognize_face(frame)

                # Debug logging for face recognition
                if frame_count % 10 == 0:  # Log every 10 frames
                    print(f"🔍 RTSP Frame {frame_count}: Found {len(faces) if faces is not None else 0} faces")
                    print(f"🧠 Face dictionary loaded: {len(face_recognizer.dictionary) if face_recognizer.dictionary else 0} people")
                    if face_recognizer.dictionary:
                        print(f"🧑 Registered people: {list(face_recognizer.dictionary.keys())}")
                        print(f"🎯 Recognition threshold: {face_recognizer.thresold}")
                    else:
                        print("⚠️ No face dictionary loaded - check if people are registered")

                # Process detection results
                detection_results = []
                if faces is not None and len(faces) > 0:
                    for i, face in enumerate(faces):
                        x1, y1, w, h = face[:4].astype(int)
                        x2, y2 = x1 + w, y1 + h

                        result = {
                            'bbox': [int(x1), int(y1), int(x2), int(y2)],
                            'confidence': float(face[14]) if len(face) > 14 else 0.0
                        }

                        # Check for face recognition match
                        if i < len(frame_features) and face_recognizer.dictionary:
                            feature = frame_features[i]
                            best_match = None
                            highest_score = 0

                            for person_id, ref_feature in face_recognizer.dictionary.items():
                                score = face_recognizer.face_recognizer.match(feature, ref_feature)

                                # Debug logging for recognition scores
                                person_name = db.get_person_name(person_id)
                                print(f"🔍 RTSP Recognition: {person_name} -> Score: {score:.3f} (threshold: {face_recognizer.thresold})")

                                if score > face_recognizer.thresold and score > highest_score:
                                    highest_score = score
                                    best_match = {
                                        'person_id': person_id,
                                        'person_name': person_name,
                                        'confidence': float(score)
                                    }

                            if best_match:
                                result.update({
                                    'person_id': best_match['person_id'],
                                    'person_name': best_match['person_name'],
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

                # Send detection results to frontend
                await sio.emit('face_detection_result', {
                    "faces": detection_results,
                    "timestamp": time.time(),
                    "frame_size": {"width": frame.shape[1], "height": frame.shape[0]}
                }, to=sid)

                if len(detection_results) > 0:
                    print(f"🔍 RTSP Detection: Sent {len(detection_results)} results to {sid}")

            except Exception as e:
                print(f"❌ Error in RTSP detection processing: {e}")

            # Minimal delay for better responsiveness
            await asyncio.sleep(0.01)

        print(f"🛑 RTSP detection processing stopped for {sid}")
        cap.release()

    except Exception as e:
        print(f"❌ Error in RTSP detection stream: {e}")
        await sio.emit('detection_error', {"error": f"RTSP detection error: {str(e)}"}, to=sid)


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

        # Draw background rectangle for text
        cv2.rectangle(overlay_frame, (x1, y1 - text_height - 10), (x1 + text_width, y1), bg_color, -1)

        # Draw text
        cv2.putText(overlay_frame, label, (x1, y1 - 5), font, font_scale, label_color, thickness)

    return overlay_frame


async def process_rtsp_with_ffmpeg_overlay(rtsp_url, output_queue, stop_event):
    """Process RTSP stream with ffmpeg and overlay detection results"""
    print(f"🎬 Starting ffmpeg RTSP processing: {rtsp_url}")

    try:
        cap = cv2.VideoCapture(rtsp_url)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        if not cap.isOpened():
            print(f"❌ Failed to open RTSP stream for ffmpeg: {rtsp_url}")
            return

        # Get video properties
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        print(f"📺 Video properties: {width}x{height} @ {fps}fps")

        frame_count = 0
        detection_results_cache = []

        while not stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                print("⚠️ Failed to read frame from RTSP stream")
                await asyncio.sleep(0.01)  # Reduced delay
                continue

            frame_count += 1

            # Run face detection every frame for lower latency
            if frame_count % 1 == 0:  # Detect every frame
                try:
                    frame_features, faces = face_recognizer.recognize_face(frame)

                    # Process detection results
                    detection_results_cache = []
                    if faces is not None and len(faces) > 0:
                        for i, face in enumerate(faces):
                            x1, y1, w, h = face[:4].astype(int)
                            x2, y2 = x1 + w, y1 + h

                            result = {
                                'bbox': [int(x1), int(y1), int(x2), int(y2)],
                                'confidence': float(face[14]) if len(face) > 14 else 0.0,
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

                                    if score > face_recognizer.thresold and score > highest_score:
                                        highest_score = score
                                        person_name = db.get_person_name(person_id)
                                        best_match = {
                                            'person_id': person_id,
                                            'person_name': person_name,
                                            'confidence': float(score)
                                        }

                                if best_match:
                                    result.update({
                                        'person_id': best_match['person_id'],
                                        'person_name': best_match['person_name'],
                                        'match_confidence': best_match['confidence'],
                                        'recognized': True
                                    })

                                    # Store latest recognition and broadcast to welcome screens
                                    recognition_data = {
                                        'type': 'recognition',
                                        'user': {
                                            'person_id': best_match['person_id'],
                                            'person_name': best_match['person_name'],
                                            'name': best_match['person_name'],
                                            'confidence': best_match['confidence'],
                                            'photo': None
                                        },
                                        'timestamp': time.time()
                                    }

                                    latest_recognition.update(recognition_data)

                                    # Broadcast to welcome screens via SocketIO
                                    for welcome_screen_sid in welcome_screens.keys():
                                        asyncio.create_task(sio.emit('recognition_result', recognition_data, to=welcome_screen_sid))

                            detection_results_cache.append(result)

                    # Send detection results to frontend for UI updates (sidebar panels)
                    if detection_results_cache:
                        for sid in detection_active.keys():
                            asyncio.create_task(sio.emit('face_detection_result', {
                                "faces": detection_results_cache,
                                "timestamp": time.time(),
                                "frame_size": {"width": frame.shape[1], "height": frame.shape[0]}
                            }, to=sid))

                except Exception as e:
                    print(f"❌ Error in face detection: {e}")

            # Draw overlays on frame using cached detection results
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

            # Minimal delay for better responsiveness
            await asyncio.sleep(0.01)  # 10ms instead of fps-based delay

        cap.release()
        print("🛑 FFmpeg RTSP processing stopped")

    except Exception as e:
        print(f"❌ Error in ffmpeg RTSP processing: {e}")




# Camera utility functions
def get_camera_index_from_device_id(device_id):
    """
    Map a device ID to an OpenCV camera index.
    This is a best-effort approach since OpenCV doesn't directly support device IDs.
    """
    try:
        import platform
        import subprocess

        if platform.system() == "Darwin":  # macOS
            # For macOS, try to enumerate cameras and match
            for i in range(10):  # Check first 10 indices
                cap = cv2.VideoCapture(i)
                if cap.isOpened():
                    ret, frame = cap.read()
                    cap.release()
                    if ret and frame is not None:
                        # This camera works, but we can't easily match device IDs
                        # For now, return the index order they appear in
                        return i
                else:
                    cap.release()
        else:
            # For other systems, try indices in order
            for i in range(10):
                cap = cv2.VideoCapture(i)
                if cap.isOpened():
                    ret, frame = cap.read()
                    cap.release()
                    if ret and frame is not None:
                        return i
                else:
                    cap.release()

        return None
    except Exception as e:
        print(f"Error mapping device ID to camera index: {e}")
        return None

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
    person_id: str
    person_name: str
    image_data: str

class AdminPasswordChange(BaseModel):
    old_id: str
    old_password: str
    new_id: str
    new_password: str
    confirm_password: str

class CameraSettings(BaseModel):
    source: Optional[str] = "default"
    device_id: Optional[str] = None
    rtsp_url: Optional[str] = None

class DisplaySettings(BaseModel):
    timer: Optional[int] = 5
    background_color: Optional[str] = "#FFE8D4"
    font_color: Optional[str] = "#032F5C"
    use_background_image: Optional[bool] = False
    background_image: Optional[str] = None
    font_family: Optional[str] = "Inter"
    font_size: Optional[str] = "medium"

class FaceDetectionRequest(BaseModel):
    image_data: str

# SocketIO Models
class FrameData(BaseModel):
    frame: str  # base64 encoded image

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
    """Get all registered people"""
    try:
        person_ids = db.get_all_person_ids()
        people = []

        for person_id in person_ids:
            person_name = db.get_person_name(person_id)
            if person_name:
                people.append({
                    'id': person_id,
                    'name': person_name
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
    """Register a new person"""
    try:
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
        features, faces = face_recognizer.recognize_face(image_cv, f"{request.person_id}.png")

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

        # Save person to database
        db_result = db.insert_into_person(request.person_id, request.person_name)

        if 'already exist' in db_result:
            return {
                'success': False,
                'message': 'person ID already exists'
            }

        # Save face image
        os.makedirs('images', exist_ok=True)
        image_path = f'images/{request.person_id}.png'
        cv2.imwrite(image_path, image_cv)

        # Recreate features dictionary with new person
        face_recognizer.create_features()

        return {
            'success': True,
            'message': 'person registered successfully',
            'person_id': request.person_id,
            'person_name': request.person_name
        }

    except Exception as e:
        return {
            'success': False,
            'message': f'Registration failed: {str(e)}'
        }

@app.delete("/api/people/{person_id}")
async def delete_person(person_id: str):
    """Delete a person"""
    try:
        result = db.delete_data_from_person(person_id)
        if result:
            # Recreate features dictionary after deletion
            face_recognizer.create_features()
            return {
                'success': True,
                'message': 'person deleted successfully'
            }
        else:
            return {
                'success': False,
                'message': 'Failed to delete person'
            }
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
            for i, face in enumerate(faces):
                # Get bounding box
                x1, y1, w, h = face[:4].astype(int)
                x2, y2 = x1 + w, y1 + h

                result = {
                    'bbox': [x1, y1, x2, y2],
                    'confidence': float(face[14]) if len(face) > 14 else 0.0
                }

                # Check if we have features and can match
                if i < len(endpoint_features) and face_recognizer.dictionary:
                    feature = endpoint_features[i]
                    best_match = None
                    highest_score = 0

                    # Compare with all known faces
                    for person_id, ref_feature in face_recognizer.dictionary.items():
                        score = face_recognizer.face_recognizer.match(feature, ref_feature)
                        if score > face_recognizer.thresold and score > highest_score:
                            highest_score = score
                            person_name = db.get_person_name(person_id)
                            best_match = {
                                'person_id': person_id,
                                'person_name': person_name,
                                'confidence': float(score)
                            }

                    if best_match:
                        result.update({
                            'person_id': best_match['person_id'],
                            'person_name': best_match['person_name'],
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
    try:
        camera_config = config_manager.get_camera_config()
        return {
            'success': True,
            'source': camera_config.get('source', 'default'),
            'device_id': camera_config.get('device_id'),
            'rtsp_url': camera_config.get('rtsp_url'),
            'use_webcam': camera_config.get('source') != 'rtsp'
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

@app.post("/api/camera/test")
async def test_camera(request: CameraSettings):
    """Test camera connection"""
    try:
        print(f"🔍 Testing camera - source: {request.source}, device_id: {request.device_id}, rtsp_url: {request.rtsp_url}")

        # Determine the video source based on settings
        if request.source == 'rtsp':
            if not request.rtsp_url:
                return {
                    'success': False,
                    'message': 'RTSP URL is required for RTSP camera source'
                }
            source = request.rtsp_url
            print(f"📡 Testing RTSP camera: {request.rtsp_url}")
        elif request.source == 'default':
            source = 0
            print(f"📷 Testing default camera (index 0)")
        elif request.source == 'device' and request.device_id:
            print(f"📷 Testing device with ID: {request.device_id}")

            # Simple mapping based on device ID patterns
            # Based on testing: BRIO is at OpenCV index 0, MacBook Air is at index 1
            # Logitech BRIO device ID starts with 'd16a9c26...' → camera index 0
            # MacBook Air device ID starts with '883bf618...' → camera index 1

            if request.device_id.startswith('d16a9c26'):
                source = 0  # Logitech BRIO → OpenCV index 0
                print(f"📷 Detected Logitech BRIO → using camera index 0")
            elif request.device_id.startswith('883bf618'):
                source = 1  # MacBook Air → OpenCV index 1
                print(f"📷 Detected MacBook Air Camera → using camera index 1")
            else:
                # For other devices, use a simple hash to map to different indices
                import hashlib
                device_hash = int(hashlib.md5(request.device_id.encode()).hexdigest()[:8], 16)
                source = device_hash % 3  # Map to 0, 1, or 2
                print(f"📷 Unknown device → hash mapping to camera index {source}")

            print(f"📷 Device {request.device_id[:12]}... → camera index: {source}")
        else:
            source = 0

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
                    return {
                        'success': False,
                        'message': f'Camera opened but no video signal (source: {source})'
                    }
            else:
                print(f"❌ Couldn't open camera source: {source}")
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
            use_background_image=request.use_background_image,
            background_image=request.background_image,
            font_family=request.font_family,
            font_size=request.font_size
        )

        if success:
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

        # Read and save the file
        contents = await file.read()

        # Save to file system
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

        return {
            'success': True,
            'message': 'Background image uploaded successfully',
            'image_url': image_data_url
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
        backgrounds_dir = "backgrounds"
        if os.path.exists(backgrounds_dir):
            for file in os.listdir(backgrounds_dir):
                if file.startswith("welcome_background"):
                    file_path = os.path.join(backgrounds_dir, file)
                    return FileResponse(file_path)

        raise HTTPException(status_code=404, detail="No background image found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# System endpoints
@app.get("/api/system/status")
async def get_system_status():
    """Get system status"""
    try:
        people = await get_people()
        return {
            "status": "online",
            "total_people": people.get("total", 0),
            "models_loaded": True,
            "database_connected": True
        }
    except Exception as e:
        return {
            "status": "error",
            "message": str(e),
            "models_loaded": False,
            "database_connected": False
        }

@app.get("/api/system/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": get_current_datetime_other_format()}

@app.get("/api/rtsp/stream")
async def rtsp_stream(request: Request):
    """Stream RTSP video feed as HTTP MJPEG stream"""
    camera_config = config_manager.get_camera_config()

    if camera_config.get('source') != 'rtsp' or not camera_config.get('rtsp_url'):
        raise HTTPException(status_code=400, detail="RTSP not configured")

    rtsp_url = camera_config['rtsp_url']

    # Create unique stream ID for this request
    stream_id = f"rtsp_{id(request)}"
    rtsp_streams[stream_id] = True

    print(f"📡 Starting RTSP stream {stream_id} from: {rtsp_url}")

    def generate_frames():
        cap = cv2.VideoCapture(rtsp_url)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Reduce latency

        if not cap.isOpened():
            print(f"❌ Failed to open RTSP stream: {rtsp_url}")
            return

        print(f"✅ RTSP stream {stream_id} opened successfully")

        try:
            while rtsp_streams.get(stream_id, False):  # Check if stream should continue
                ret, frame = cap.read()
                if not ret:
                    break

                # Encode frame as JPEG
                _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])

                # Yield frame in multipart format
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

        finally:
            cap.release()
            if stream_id in rtsp_streams:
                del rtsp_streams[stream_id]
            print(f"🛑 RTSP stream {stream_id} closed")

    return StreamingResponse(
        generate_frames(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


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
    stop_event = threading.Event()

    # Start the background processing thread
    processing_task = asyncio.create_task(
        process_rtsp_with_ffmpeg_overlay(rtsp_url, frame_queue, stop_event)
    )

    def generate_frames():
        try:
            while ffmpeg_streams.get(stream_id, False):
                try:
                    # Get frame from queue with shorter timeout for responsiveness
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

@app.get("/api/rtsp/test")
async def test_rtsp():
    """Test RTSP connection without streaming"""
    camera_config = config_manager.get_camera_config()

    if camera_config.get('source') != 'rtsp' or not camera_config.get('rtsp_url'):
        return {"success": False, "error": "RTSP not configured"}

    rtsp_url = camera_config['rtsp_url']
    print(f"📡 Testing RTSP connection: {rtsp_url}")

    try:
        cap = cv2.VideoCapture(rtsp_url)
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

@app.post("/api/rtsp/stop")
async def stop_rtsp_streams():
    """Stop all active RTSP streams"""
    rtsp_stream_count = len(rtsp_streams)
    ffmpeg_stream_count = len(ffmpeg_streams)

    rtsp_streams.clear()
    ffmpeg_streams.clear()

    total_stopped = rtsp_stream_count + ffmpeg_stream_count
    print(f"🛑 Stopped {rtsp_stream_count} RTSP streams and {ffmpeg_stream_count} FFmpeg streams")

    return {
        "success": True,
        "stopped_rtsp_streams": rtsp_stream_count,
        "stopped_ffmpeg_streams": ffmpeg_stream_count,
        "total_stopped": total_stopped
    }

if __name__ == "__main__":
    # Run the server with SocketIO
    uvicorn.run(
        "api:socket_app",  # Use the SocketIO app instead of FastAPI app directly
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )