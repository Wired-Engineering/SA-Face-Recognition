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
    │ Browser     │                              │ PostgreSQL/ │
    │ WebCamera   │                              │  SQLite DB  │
    │ Media API   │                              │ + AI Models │
    └─────────────┘                              └─────────────┘
```

## 🚀 Quick Start

### Prerequisites

- **Node.js** 18+ and **pnpm**
- **Python** 3.8+ < 3.12 with pip
- **Webcam** or RTSP camera access

### Installation

1. **Clone and setup**
   ```bash
   git clone <repository>
   cd SA-Face-Recognition
   pnpm install
   ```

2. **Install Python dependencies (Linux/Mac)**
   ```bash
   pip3 install -r src/python/requirements.txt
   cd src/python
   sh download_weights.sh
   cd ../..
   ```

3. **Configure database (optional)**
   ```bash
   # For local development, SQLite is used by default (system/Attendance.db)
   # For Replit/production, set DATABASE_URL environment variable
   # See .env.example for configuration options
   ```

4. **Start all services**
   ```bash
   pnpm start
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

- **Face Detection**: SCRFD (det_10g.onnx)
- **Face Recognition**: ArcFace (w600k_r50.onnx)
- **Face Search**: FAISS vector similarity search
- **Format**: ONNX (cross-platform)
- **Performance**: Real-time on CPU

Default admin: `admin` / `1234`

## 🔧 Configuration

### Database Settings - Hybrid Architecture

The system uses a **HYBRID** database setup for security and flexibility:

**Database File**: `system/Attendance.db` (SQLite)

**Tables**:
| Table | Local (SQLite) | Cloud (PostgreSQL) | Contains |
|-------|---------------|-------------------|----------|
| **CREDENTIALS** | Always ✅ | Never ❌ | Admin login credentials |
| **FR_REGISTRATIONS** | Default ✅ | Optional (when DATABASE_URL set) | Person registrations with ID, Name, Title, Registration_id |

**Configuration**:
- **Local Development**: Leave `DATABASE_URL` unset → all tables use SQLite
- **Replit/Production**: Set `DATABASE_URL` → FR_REGISTRATIONS table moves to PostgreSQL
- **Connection Pooling**: Enabled for PostgreSQL FR_REGISTRATIONS table (1-10 connections)
- **Security**: Admin credentials never leave local machine

See `.env.example` and `DATABASE_MIGRATION.md` for detailed configuration and migration guide.

### Database Migration

When migrating from SQLite-only to PostgreSQL, use these migration scripts:

1. **Schema Migration** (migrate_schema.py)
   ```bash
   python migrate_schema.py
   ```
   - Renames old tables: ADMIN → CREDENTIALS, PERSON → FR_REGISTRATIONS
   - Updates column: Registration → Registration_id
   - Only needed if you have an old SQLite database
   - Run this FIRST before data migration

2. **Data Migration** (migrate_data_to_postgres.py)
   ```bash
   # Set your database URL in .env first
   # DEV_DATABASE_URL=postgresql://username:password@localhost:5432/registrations_dev

   python migrate_data_to_postgres.py
   ```
   - Copies all FR_REGISTRATIONS data from SQLite to PostgreSQL
   - Detects and skips duplicate records
   - Three cleanup options: keep as backup, clear data, or drop table
   - Run this AFTER schema migration and setting DATABASE_URL

**Migration Order**:
1. Run `migrate_schema.py` (if you have old table names)
2. Set `DEV_DATABASE_URL` or `DATABASE_URL` in `.env`
3. Run `migrate_data_to_postgres.py` (to copy data to cloud)
4. Start application: `pnpm start`

**Automatic Migration in Docker**:
- Docker containers automatically run migrations on startup
- Schema migration (PERSON → FR_REGISTRATIONS) runs if old tables detected
- Data migration to PostgreSQL runs if DEV_DATABASE_URL or DATABASE_URL is set
- After successful PostgreSQL migration, SQLite FR_REGISTRATIONS table is dropped
- Safe to restart containers - migrations are idempotent (skip duplicates)

**Manual Migration in Docker** (if needed):
```bash
# Schema migration
docker exec -it <container_name> python migrate_schema.py

# Data migration
docker exec -it <container_name> python migrate_data_to_postgres.py
```

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

### Replit Deployment

1. **Create PostgreSQL database for FR_REGISTRATIONS table**
   - Use Replit Database tool to create a PostgreSQL database
   - Recommended name: `registrations`
   - `DATABASE_URL` will be automatically set in environment variables
   - This will store only the FR_REGISTRATIONS table

3. **Build React app**
   ```bash
   pnpm build
   ```

4. **Configure environment**
   ```bash
   export NODE_ENV=production
   export PYTHON_ENV=production
   # DATABASE_URL is automatically set by Replit
   ```

5. **Database tables**
   - FR_REGISTRATIONS table created automatically in PostgreSQL
   - CREDENTIALS table remains in SQLite (`system/Attendance.db`)
   - Default admin credentials: `admin` / `1234` (stored locally in SQLite)

### Other Platforms

1. **Set database credentials (optional)**
   ```bash
   # To use PostgreSQL for FR_REGISTRATIONS table:
   export DATABASE_URL=postgresql://username:password@host:port/database

   # Leave unset to use SQLite for all tables (local development)
   ```

2. **Install dependencies**
   ```bash
   pip3 install -r src/python/requirements.txt
   pnpm install
   ```

3. **Start services**
   ```bash
   pnpm start
   ```

**Note**: SQLite database file (`system/Attendance.db`) is always required for the CREDENTIALS table, even when using PostgreSQL for FR_REGISTRATIONS table.

## 📝 License

Private project for Signature Aviation

## 🤝 Support

- 📚 **API Docs**: http://localhost:8000/api/docs
- 🔍 **Debug**: Check browser console and server logs
- 🛠️ **Issues**: Contact development team

---

**Built with ❤️ using React, Express.js, FastAPI, and OpenCV**
