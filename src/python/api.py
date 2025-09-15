from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
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
from contextlib import asynccontextmanager

# SocketIO imports
import socketio

from DatabaseManager import MySqlite3Manager
from utils import get_current_datetime_other_format
from My_Face_recognizer import FaceRecognizer

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
    description="Face recognition system for student attendance",
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
face_recognizer = FaceRecognizer(thresold=0.5, draw=True)

# SocketIO globals
detection_active: Dict[str, bool] = {}
welcome_screens: Dict[str, bool] = {}  # Track welcome screen connections
latest_recognition: Dict = {}  # Store latest recognition result

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

@sio.event
async def start_detection(sid, data):
    """Start face detection for a client"""
    print(f"🔍 Starting face detection for client {sid}")
    detection_active[sid] = True
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

                    for student_id, ref_feature in face_recognizer.dictionary.items():
                        score = face_recognizer.face_recognizer.match(feature, ref_feature)
                        if score > face_recognizer.thresold and score > highest_score:
                            highest_score = score
                            student_name = db.get_student_name(student_id)
                            best_match = {
                                'student_id': student_id,
                                'student_name': student_name,
                                'confidence': float(score)
                            }

                    if best_match:
                        result.update({
                            'student_id': best_match['student_id'],
                            'student_name': best_match['student_name'],
                            'match_confidence': best_match['confidence'],
                            'recognized': True
                        })

                        # Store latest recognition for polling endpoints
                        recognition_data = {
                            'type': 'recognition',
                            'user': {
                                'student_id': best_match['student_id'],
                                'student_name': best_match['student_name'],
                                'name': best_match['student_name'],
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
                            'student_id': 'UNKNOWN',
                            'student_name': 'Unknown Person',
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

class StudentRegistration(BaseModel):
    student_id: str
    student_name: str
    image_data: str

class AdminPasswordChange(BaseModel):
    old_id: str
    old_password: str
    new_id: str
    new_password: str
    confirm_password: str

class CameraSettings(BaseModel):
    rtsp_url: Optional[str] = ""

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

# Student management endpoints
@app.get("/api/students")
async def get_students():
    """Get all registered students"""
    try:
        student_ids = db.get_all_student_ids()
        students = []

        for student_id in student_ids:
            student_name = db.get_student_name(student_id)
            if student_name:
                students.append({
                    'id': student_id,
                    'name': student_name
                })

        return {
            'success': True,
            'students': students,
            'total': len(students)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/students/register")
async def register_student(request: StudentRegistration):
    """Register a new student"""
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
        features, faces = face_recognizer.recognize_face(image_cv, f"{request.student_id}.png")

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

        # Save student to database
        db_result = db.insert_into_student(request.student_id, request.student_name)

        if 'already exist' in db_result:
            return {
                'success': False,
                'message': 'Student ID already exists'
            }

        # Save face image
        os.makedirs('images', exist_ok=True)
        image_path = f'images/{request.student_id}.png'
        cv2.imwrite(image_path, image_cv)

        # Recreate features dictionary with new student
        face_recognizer.create_features()

        return {
            'success': True,
            'message': 'Student registered successfully',
            'student_id': request.student_id,
            'student_name': request.student_name
        }

    except Exception as e:
        return {
            'success': False,
            'message': f'Registration failed: {str(e)}'
        }

@app.delete("/api/students/{student_id}")
async def delete_student(student_id: str):
    """Delete a student"""
    try:
        result = db.delete_data_from_student(student_id)
        if result:
            # Recreate features dictionary after deletion
            face_recognizer.create_features()
            return {
                'success': True,
                'message': 'Student deleted successfully'
            }
        else:
            return {
                'success': False,
                'message': 'Failed to delete student'
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
                    for student_id, ref_feature in face_recognizer.dictionary.items():
                        score = face_recognizer.face_recognizer.match(feature, ref_feature)
                        if score > face_recognizer.thresold and score > highest_score:
                            highest_score = score
                            student_name = db.get_student_name(student_id)
                            best_match = {
                                'student_id': student_id,
                                'student_name': student_name,
                                'confidence': float(score)
                            }

                    if best_match:
                        result.update({
                            'student_id': best_match['student_id'],
                            'student_name': best_match['student_name'],
                            'match_confidence': best_match['confidence'],
                            'recognized': True
                        })
                    else:
                        result.update({
                            'student_id': 'UNKNOWN',
                            'student_name': 'Unknown Person',
                            'match_confidence': 0.0,
                            'recognized': False
                        })
                else:
                    result.update({
                        'student_id': 'UNKNOWN',
                        'student_name': 'Unknown Person',
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
        rtsp_url = load_rtsp_settings()
        return {
            'rtsp_url': rtsp_url,
            'use_webcam': not bool(rtsp_url)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/camera/settings")
async def update_camera_settings(request: CameraSettings):
    """Update camera settings"""
    try:
        save_rtsp_settings(request.rtsp_url)
        return {
            'success': True,
            'message': 'Camera source updated successfully'
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/camera/test")
async def test_camera(request: CameraSettings):
    """Test camera connection"""
    try:
        source = request.rtsp_url if request.rtsp_url else 0
        cap = cv2.VideoCapture(source)

        if cap.isOpened():
            ret, frame = cap.read()
            cap.release()

            if ret and frame is not None:
                return {
                    'success': True,
                    'message': 'Camera connection successful'
                }

        return {
            'success': False,
            'message': 'Failed to connect to camera'
        }

    except Exception as e:
        return {
            'success': False,
            'message': f'Camera test failed: {str(e)}'
        }

# System endpoints
@app.get("/api/system/status")
async def get_system_status():
    """Get system status"""
    try:
        students = await get_students()
        return {
            "status": "online",
            "total_students": students.get("total", 0),
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

if __name__ == "__main__":
    # Run the server with SocketIO
    uvicorn.run(
        "api:socket_app",  # Use the SocketIO app instead of FastAPI app directly
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )