# 🛡️ Signature Aviation - Face Recognition System

A modern, full-stack face recognition application for person attendance and access control, built with React, Express.js, and FastAPI.

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   React Frontend│    │  Express.js     │    │   FastAPI       │
│   (Port 5173)   │◄──►│  Middleware     │◄──►│   Backend       │
│   Mantine UI    │    │  (Port 3001)    │    │   (Port 8000)   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │              ┌─────────────────┐              │
         │              │  File Uploads   │              │
         │              │  CORS Handling  │              │
         │              │  Proxy/Gateway  │              │
         │              └─────────────────┘              │
         │                                               │
    ┌─────────────┐                              ┌─────────────┐
    │ Browser     │                              │ SQLite DB + │
    │ WebCamera   │                              │ AI Models   │
    │ Media API   │                              │ Face Data   │
    └─────────────┘                              └─────────────┘
```

## ✨ Features

- 🎯 **Real-time Face Recognition** - Webcam & RTSP stream support
- 👤 **person Management** - Register, update, delete people
- 🔐 **Admin Authentication** - Secure login with password management
- 📊 **Attendance Tracking** - Automatic logging with timestamps
- ⚙️ **System Settings** - Camera configuration, display preferences
- 📱 **Responsive UI** - Modern interface with Mantine components
- 🚀 **RESTful API** - Clean separation with comprehensive endpoints
- 🤖 **AI-Powered** - ONNX models for detection and recognition

## 🚀 Quick Start

### Prerequisites

- **Node.js** 18+ and **ppnpm**
- **Python** 3.8+ with pip
- **Webcam** or RTSP camera access

### Installation

1. **Clone and setup**
   ```bash
   git clone <repository>
   cd SA-Face-Recognition
   ppnpm install
   ```

2. **Install Python dependencies**
   ```bash
   cd src/python
   pip3 install -r requirements.txt
   cd ../..
   ```

3. **Start all services**
   ```bash
   pnpm dev:all
   ```

### Individual Services

```bash
# Frontend only (React + Vite)
pnpm dev

# Express middleware only
pnpm server

# Python API only
pnpm python-api
```

## 🔗 Service Endpoints

| Service | URL | Description |
|---------|-----|-------------|
| **React App** | http://localhost:5173 | Main application interface |
| **Express API** | http://localhost:3001 | Middleware and file uploads |
| **FastAPI Docs** | http://localhost:8000/docs | Interactive API documentation |
| **Health Check** | http://localhost:3001/health | System status |

## 📚 API Reference

### 🔐 Authentication
```http
POST /api/auth/login
POST /api/auth/change-password
```

### 👥 person Management
```http
GET    /api/people
POST   /api/people/register
DELETE /api/people/{id}
```

### 🎯 Face Recognition
```http
POST /api/recognition/detect
POST /api/upload/face-image
```

### 📷 Camera Management
```http
GET  /api/camera/settings
POST /api/camera/settings
POST /api/camera/test
```

### ⚙️ System Status
```http
GET /api/system/status
GET /api/system/health
```

## 🗂️ Project Structure

```
SA-Face-Recognition/
├── 📁 src/
│   ├── 📁 components/          # React components
│   │   ├── AppShell.jsx        # Main layout
│   │   ├── LoginPage.jsx       # Authentication
│   │   ├── RegistrationPage.jsx# person registration
│   │   ├── DetectionPage.jsx   # Face recognition
│   │   ├── SettingsPage.jsx    # System settings
│   │   └── WelcomeScreen.jsx   # Dashboard
│   ├── 📁 services/
│   │   └── api.js              # API client & utilities
│   └── 📁 python/              # Python backend
│       ├── main.py             # FastAPI server
│       ├── face_recognition_api.py # Core AI logic
│       ├── DatabaseManager.py  # Database operations
│       ├── utils.py            # Helper functions
│       ├── 📁 model/           # AI models (ONNX)
│       ├── 📁 images/          # person face images
│       └── 📁 system/          # Config & database
├── 📄 server.js                # Express middleware
├── 📄 package.json             # Node.js dependencies
├── 📄 ICON_MAPPING.md          # UI icon reference
└── 📄 README.md               # This file
```

## 🤖 AI Models

The system uses pre-trained ONNX models for optimal performance:

- **Face Detection**: YuNet 2023 (232KB)
- **Face Recognition**: Fast Recognition Model (7.3MB)
- **Format**: ONNX (cross-platform)
- **Performance**: Real-time on CPU

## 💾 Database Schema

### Admin Table
```sql
CREATE TABLE ADMIN (
    Name TEXT,
    ID TEXT,
    Password TEXT
);
```

### person Table
```sql
CREATE TABLE person (
    Id TEXT PRIMARY KEY,
    Name TEXT
);
```

Default admin: `admin` / `1234`

## 🔧 Configuration

### Camera Settings
- **Webcam**: Automatically detected via browser API
- **RTSP Stream**: Configure via Settings page
- **Resolution**: 1280x720 @ 30fps (default)

### Face Recognition
- **Detection Confidence**: 90%
- **Recognition Threshold**: 0.363
- **Image Format**: JPEG/PNG/WebP
- **Max File Size**: 10MB

## 🛠️ Development

### Adding New Components
1. Create in `src/components/`
2. Import in `AppShell.jsx`
3. Add navigation if needed

### API Development
1. **Python**: Add endpoints in `src/python/main.py`
2. **Express**: Add middleware in `server.js`
3. **React**: Update `src/services/api.js`

### Database Changes
1. Modify `DatabaseManager.py`
2. Update API models in `main.py`
3. Restart Python service

## 🧪 Testing

```bash
# Lint code
pnpm lint

# Test API endpoints
curl http://localhost:3001/health

# Check Python API
curl http://localhost:8000/api/system/health
```

## 🚀 Production Deployment

1. **Build React app**
   ```bash
   pnpm build
   ```

2. **Configure environment**
   ```bash
   export NODE_ENV=production
   export PYTHON_ENV=production
   ```

## 📝 License

Private project for Signature Aviation

## 🤝 Support

- 📚 **API Docs**: http://localhost:8000/docs
- 🔍 **Debug**: Check browser console and server logs
- 🛠️ **Issues**: Contact development team

---

**Built with ❤️ using React, Express.js, FastAPI, and OpenCV**
