# Signature Aviation Face Recognition System - Claude Documentation

## Project Overview

This is a comprehensive face recognition system built for Signature Aviation, featuring real-time face detection, person registration, and a dynamic welcome screen display system. The application combines React frontend with FastAPI backend and includes a sophisticated popup window system for displaying recognition results.

## Architecture

### Frontend (React + Vite)
- **Framework**: React 18 with Vite build system
- **UI Library**: Mantine v7 for modern, accessible components
- **State Management**: React hooks and localStorage
- **Real-time Communication**: Socket.IO client for live face detection data
- **Icons**: Tabler Icons for consistent iconography

### Backend (Python FastAPI)
- **Framework**: FastAPI with async support
- **Real-time**: Socket.IO server for WebSocket connections
- **Database**: SQLite with custom MySqlite3Manager
- **Face Recognition**: Custom FaceRecognizer with OpenCV and face recognition libraries
- **Image Processing**: PIL, OpenCV for image handling

### Communication
- **REST API**: Standard HTTP endpoints for CRUD operations
- **WebSocket (Socket.IO)**: Real-time face detection and recognition events
- **File Upload**: Multer middleware for image processing

## Key Features

### 1. Face Recognition System
- **Live Detection**: Real-time camera feed with face detection overlay
- **person Registration**: Register new people with face encoding
- **Recognition Confidence**: Configurable threshold with confidence scoring
- **Multiple Camera Support**: Webcam and RTSP camera source options

### 2. Welcome Screen Popup System
- **Single Persistent Window**: Only one popup window at a time
- **User Queue**: Cycles through recognized users automatically
- **Configurable Display**: Timer duration, background/font colors
- **Manual Control**: Header button to open/close popup
- **Real-time Updates**: Live recognition data via Socket.IO
- **Settings Integration**: Test mode with auto-refresh on save

### 3. Admin Panel
- **Authentication**: Secure admin login system
- **User Management**: Add, delete, and manage registered people
- **Camera Configuration**: RTSP URL setup and camera testing
- **Display Settings**: Customize welcome screen appearance
- **System Monitoring**: Connection status and health checks

## File Structure

```
SA-Face-Recognition/
├── public/
│   ├── welcome-popup.html          # Standalone welcome screen popup
│   └── ApplicationIcon/            # Application icons and assets
├── src/
│   ├── components/
│   │   ├── AppShell.jsx           # Main application shell with navigation
│   │   ├── DetectionPage.jsx      # Live face detection interface
│   │   ├── LoginPage.jsx          # Admin authentication
│   │   ├── RegistrationPage.jsx   # person registration form
│   │   ├── SettingsPage.jsx       # System configuration
│   │   └── WelcomeScreen.jsx      # Welcome screen component (legacy)
│   ├── services/
│   │   ├── api.js                 # REST API service layer
│   │   └── welcomePopup.js        # Welcome popup window management
│   ├── python/
│   │   ├── api.py                 # FastAPI backend server
│   │   ├── DatabaseManager.py    # SQLite database operations
│   │   ├── My_Face_recognizer.py  # Face recognition logic
│   │   └── utils.py               # Utility functions
│   ├── App.jsx                    # Root React component
│   └── main.jsx                   # Application entry point
├── server.js                      # Express proxy server
├── package.json                   # Node.js dependencies
└── vite.config.js                # Vite build configuration
```

## Setup Instructions

### Prerequisites
- Node.js 18+ with pnpm
- Python 3.8+ with pip
- OpenCV and face recognition libraries
- SQLite3

### Frontend Setup
```bash
# Install dependencies
pnpm install

# Start development server
pnpm run dev
```

### Backend Setup
```bash
# Install Python dependencies
pip install fastapi uvicorn opencv-python face-recognition pillow python-socketio

# Start FastAPI server
cd src/python
python api.py
```

### Proxy Server
```bash
# Start Express proxy (bridges React and FastAPI)
node server.js
```

## API Endpoints

### Authentication
- `POST /api/auth/login` - Admin login
- `POST /api/auth/change-password` - Change admin credentials

### person Management
- `GET /api/people` - List all registered people
- `POST /api/people/register` - Register new person with face data
- `DELETE /api/people/{person_id}` - Remove person

### Face Recognition
- `POST /api/recognition/detect` - Process image for face detection
- `GET /api/recognition/latest` - Get latest recognition result (for popup polling)

### Camera Settings
- `GET /api/camera/settings` - Get camera configuration
- `POST /api/camera/settings` - Update camera settings
- `POST /api/camera/test` - Test camera connection

### System
- `GET /api/system/status` - System health and statistics
- `GET /api/system/health` - Health check endpoint

## Socket.IO Events

### Client to Server
- `start_detection` - Begin face detection
- `stop_detection` - Stop face detection
- `process_frame` - Send video frame for processing
- `register_welcome_screen` - Register popup window for recognition updates
- `unregister_welcome_screen` - Unregister popup window

### Server to Client
- `face_detection_result` - Face detection results with bounding boxes
- `recognition_result` - Recognition data broadcast to welcome screens
- `detection_started/stopped` - Detection state changes
- `welcome_screen_registered` - Confirmation of popup registration

## Welcome Screen System

### Architecture
The welcome screen system consists of three main components:

1. **Popup Service** (`src/services/welcomePopup.js`)
   - Manages single persistent popup window
   - Handles opening/closing and settings updates
   - Provides utility functions for popup control

2. **Standalone HTML** (`public/welcome-popup.html`)
   - Self-contained popup window with Socket.IO client
   - User queue management and cycling logic
   - Configurable appearance and behavior
   - Fallback HTTP polling when Socket.IO unavailable

3. **Integration Points**
   - Header navigation button for manual control
   - Settings page with test mode and auto-refresh
   - Backend broadcasting of recognition events

### User Flow
1. **Manual Open**: Click "Welcome Screen" in header navigation
2. **Live Recognition**: Backend detects face and broadcasts to popup
3. **User Display**: Shows user info for configured timer duration
4. **Queue Management**: Multiple users cycle through automatically
5. **Manual Close**: User closes popup window when done

### Configuration
- **Timer Duration**: How long each user is displayed (seconds)
- **Background Color**: Popup background color (hex)
- **Font Color**: Text color for user information (hex)
- **Persistent Mode**: Window stays open until manually closed

## Development Notes

### Face Recognition Flow
1. Camera captures frames → Frontend (DetectionPage)
2. Frames sent via Socket.IO → Backend (api.py)
3. OpenCV processes frames → Face detection/recognition
4. Results broadcast to:
   - Detection interface (bounding boxes, overlays)
   - Welcome screen popups (user information)

### Database Schema
- **people Table**: person_id (PK), person_name
- **Admin Table**: admin_id (PK), admin_name, password_hash
- **Face Encodings**: Stored as pickle files in `images/` directory

### Security Considerations
- Admin password hashing and secure authentication
- Input validation on all API endpoints
- CORS configuration for specific origins only
- File upload size limits and type validation

### Performance Optimizations
- Face encoding caching in memory
- Frame processing rate limiting
- Connection pooling for database operations
- Efficient Socket.IO event handling

## Troubleshooting

### Common Issues

1. **Camera Not Working**
   - Check camera permissions in browser
   - Verify camera device availability
   - Test RTSP URL if using external camera

2. **Face Recognition Inaccurate**
   - Adjust recognition threshold in backend
   - Ensure good lighting for face registration
   - Re-register users with poor recognition rates

3. **Welcome Popup Not Opening**
   - Check popup blocker settings
   - Verify Socket.IO connection status
   - Check browser console for JavaScript errors

4. **Socket.IO Connection Issues**
   - Ensure FastAPI server is running on port 8000
   - Check CORS configuration in backend
   - Verify proxy server is forwarding requests correctly

### Debug Commands
```bash
# Check backend server status
curl http://localhost:8000/api/system/health

# Test face recognition endpoint
curl -X POST http://localhost:8000/api/recognition/detect \
  -H "Content-Type: application/json" \
  -d '{"image_data": "base64_encoded_image"}'

# Monitor Socket.IO events
# Open browser dev tools → Network → WS to see WebSocket traffic
```

## Future Enhancements

### Planned Features
- Multiple camera feeds simultaneously
- Recognition history and analytics
- Email/SMS notifications for specific users
- Integration with access control systems
- Mobile app for remote monitoring
- Attendance tracking and reporting

### Performance Improvements
- GPU acceleration for face recognition
- Redis caching for recognition results
- Load balancing for multiple camera sources
- Database optimization and indexing

### UI/UX Enhancements
- Dark mode support
- Customizable dashboard layouts
- Advanced filtering and search
- Real-time system monitoring charts
- Accessibility improvements

## License

This project is proprietary software developed for Signature Aviation. All rights reserved.

## Support

For technical support or questions about this system, please contact the development team or refer to the project documentation.

---

*Generated with Claude Code - Documentation created for Signature Aviation Face Recognition System*