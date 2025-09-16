# Container/Remote Deployment Guide

## Architecture Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Admin Laptop  │    │  Server/Docker  │    │ Welcome Display │
│                 │    │                 │    │                 │
│  Configuration  │◄──►│   FastAPI       │◄──►│  Popup Window   │
│  Interface      │    │   Face Recog    │    │  (Kiosk Mode)   │
│  (Full App)     │    │   RTSP Stream   │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## Backend (Container/Server)

### Docker Setup
```dockerfile
FROM python:3.9

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY src/python/ .
COPY src/python/system/ ./system/
COPY images/ ./images/

EXPOSE 8000

CMD ["python", "api.py"]
```

### Docker Compose
```yaml
version: '3.8'
services:
  face-recognition:
    build: .
    ports:
      - "8000:8000"
    volumes:
      - ./config:/app/system
      - ./face-data:/app/images
    environment:
      - HOST=0.0.0.0
      - PORT=8000
```

### Network Configuration
Ensure the server is accessible from both admin laptop and welcome display:
```bash
# Run on server/container
python api.py --host 0.0.0.0 --port 8000
```

## Admin Interface (Laptop)

Access full configuration interface at:
```
http://YOUR_SERVER_IP:8000
```

Features available:
- Camera settings (RTSP configuration)
- Person registration
- Display customization
- System monitoring
- Live detection testing

## Welcome Display (Dedicated Screen)

### Direct Access Method
Open directly in browser:
```
http://YOUR_SERVER_IP:8000/welcome-popup.html
```

### Kiosk Mode Setup

#### Chrome/Chromium
```bash
google-chrome --kiosk --no-sandbox --disable-infobars \
  --disable-features=TranslateUI \
  --disable-background-mode \
  http://YOUR_SERVER_IP:8000/welcome-popup.html
```

#### Firefox
```bash
firefox --kiosk http://YOUR_SERVER_IP:8000/welcome-popup.html
```

### Auto-Start Configuration

#### Linux (systemd)
Create `/etc/systemd/system/welcome-display.service`:
```ini
[Unit]
Description=Welcome Display Kiosk
After=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/chromium --kiosk --no-sandbox http://YOUR_SERVER_IP:8000/welcome-popup.html
Restart=always
User=display
Environment=DISPLAY=:0

[Install]
WantedBy=graphical-session.target
```

#### Windows (Auto-start)
Add to Windows startup folder:
```bat
@echo off
start chrome --kiosk http://YOUR_SERVER_IP:8000/welcome-popup.html
```

#### Raspberry Pi (Autostart)
Add to `/home/pi/.config/lxsession/LXDE-pi/autostart`:
```
@chromium-browser --kiosk --no-sandbox http://YOUR_SERVER_IP:8000/welcome-popup.html
```

## Features of Standalone Welcome Display

### Independent Operation
- Runs completely separate from admin interface
- Real-time recognition via Socket.IO
- Automatic user cycling
- Configurable display timer
- Custom branding/colors

### Configuration Sync
- Settings changed on admin interface automatically apply
- No need to restart welcome display
- Live preview when testing settings

### Network Requirements
- HTTP access to server (port 8000)
- WebSocket support for real-time updates
- Stable network connection recommended

## Production Considerations

### Security
```nginx
# Nginx reverse proxy with SSL
server {
    listen 443 ssl;
    server_name your-domain.com;

    location / {
        proxy_pass http://localhost:8000;
        # ... SSL and proxy config
    }

    # Restrict admin access
    location /settings {
        allow 192.168.1.0/24;  # Admin network
        deny all;
        proxy_pass http://localhost:8000;
    }
}
```

### Monitoring
- Health check: `GET /api/system/health`
- Stream status: `GET /api/rtsp/test`
- System metrics: `GET /api/system/status`

### Backup/Recovery
Important files to backup:
- `system/config.yaml` - Configuration
- `system/Attendance.db` - Database
- `images/` - Face encodings

## Troubleshooting

### Welcome Display Not Connecting
1. Check network connectivity: `ping YOUR_SERVER_IP`
2. Test direct access: `curl http://YOUR_SERVER_IP:8000/api/system/health`
3. Verify WebSocket: Check browser console for Socket.IO errors

### RTSP Stream Issues
1. Test connection: `GET /api/rtsp/test`
2. Check camera accessibility from server
3. Verify RTSP URL format and credentials

### Performance Optimization
- Use dedicated display hardware (Raspberry Pi, NUC)
- Optimize network bandwidth for RTSP streams
- Consider local caching for static assets

## Example Commands

### Start server in container
```bash
docker run -p 8000:8000 -v ./config:/app/system face-recognition
```

### Test from admin laptop
```bash
curl http://server-ip:8000/api/system/health
```

### Launch welcome display
```bash
chromium --kiosk http://server-ip:8000/welcome-popup.html
```

This setup allows complete separation of concerns: admin on laptop, processing on server, display on dedicated screen.