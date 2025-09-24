# 🛡️ Signature Aviation - Face Recognition System

A face recognition application for welcoming guests into an area - built with React, Express.js, and FastAPI.

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

## 🚀 Quick Start

### Prerequisites

- **Node.js** 18+ and **ppnpm**
- **Python** 3.8+ < 3.12 with pip
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
| **Health Check** | http://localhost:3001/api/system/health | System status |

## 🤖 AI Models

The system uses pre-trained ONNX models for optimal performance:

- **Face Detection**: MediaPipe
- **Face Recognition**: Fast Recognition Model (38.7MB)
- **Format**: ONNX (cross-platform)
- **Performance**: Real-time on CPU

Default admin: `admin` / `1234`

## 🔧 Configuration

### Camera Settings
- **Webcam**: Automatically detected via browser API
- **RTSP Stream**: Configure via Settings page
- **Resolution**: 1280x720 @ 30fps (default)

### Face Recognition
- **Detection Confidence**: 90%
- **Recognition Threshold**: 0.363
- **Image Format**: JPEG/PNG
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

- 📚 **API Docs**: http://localhost:8000/api/docs
- 🔍 **Debug**: Check browser console and server logs
- 🛠️ **Issues**: Contact development team

---

**Built with ❤️ using React, Express.js, FastAPI, and OpenCV**
