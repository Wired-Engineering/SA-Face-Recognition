#!/bin/bash
set -e

echo "🚀 Starting Signature Aviation Face Recognition System"
echo "======================================================"

# Create required directories
mkdir -p /var/log/supervisor /var/log/nginx

# Check and download model weights if missing
echo "🧠 Model Weights Check:"
echo "======================"
cd /app/src/python
if [ ! -f "weights/det_2.5g.onnx" ] || [ ! -f "weights/det_10g.onnx" ] || [ ! -f "weights/w600k_r50.onnx" ]; then
    echo "📥 Missing model weights detected - downloading..."
    sh download_weights.sh
    echo "✅ Model weights ready"
else
    echo "✅ All model weights present"
fi
echo ""

# Database Migration Check
echo "🗄️  Database Migration Check:"
echo "============================"
cd /app

# Check if SQLite database exists and needs migration
if [ -f "src/python/system/Attendance.db" ]; then
    echo "📊 SQLite database found - checking for old schema..."

    # Run schema migration (idempotent - safe to run multiple times)
    if python migrate_schema.py <<EOF 2>&1
yes
EOF
    then
        echo "✅ Schema migration completed successfully"
    else
        echo "⚠️  Schema migration had warnings (this may be normal if already migrated)"
    fi

    # Check if PostgreSQL is configured for data migration
    if [ -n "$DEV_DATABASE_URL" ] || [ -n "$DATABASE_URL" ]; then
        DB_ENV_VAR="${DEV_DATABASE_URL:-$DATABASE_URL}"
        echo "🔌 PostgreSQL URL detected - checking data migration..."

        # Run data migration (skips duplicates, safe to run multiple times)
        # Option 3 = drop SQLite FR_REGISTRATIONS table after migration
        if python migrate_data_to_postgres.py <<EOF 2>&1
yes
3
EOF
        then
            echo "✅ Database migration to PostgreSQL complete"
        else
            echo "⚠️  PostgreSQL migration failed - will use SQLite"
            echo "   Application will continue to start..."
        fi
    else
        echo "ℹ️  No PostgreSQL URL set - using SQLite only"
    fi
else
    echo "ℹ️  No existing database - will be created on first run"
fi
echo ""

# GPU Hardware Detection and Diagnostics
echo "🔍 GPU Hardware Detection:"
echo "=========================="

# Check if running in Docker
if [ -f /.dockerenv ] || [ -f /proc/1/cgroup ]; then
    echo "🐳 Running in Docker container"
    echo ""
    echo "🧠 GPU Hardware Detection:"
    echo "=========================="
    cd /app/src/python

    # Auto-detect GPU acceleration based on device passthrough
    GPU_DETECTED="false"
    GPU_TYPE=""

    # Check for NVIDIA GPU first (most common for AI workloads)
    if command -v nvidia-smi &> /dev/null; then
        echo "✅ NVIDIA GPU detected (via nvidia-smi)"
        GPU_DETECTED="true"
        GPU_TYPE="NVIDIA"
        export ENABLE_GPU_ACCELERATION=true
        export GPU_BACKEND_TYPE=nvidia
    elif [ -e "/dev/nvidia0" ] || [ -e "/dev/nvidiactl" ]; then
        echo "✅ NVIDIA GPU devices detected (/dev/nvidia*)"
        GPU_DETECTED="true"
        GPU_TYPE="NVIDIA"
        export ENABLE_GPU_ACCELERATION=true
        export GPU_BACKEND_TYPE=nvidia
    # Check for Intel/AMD GPU (DRI devices)
    elif [ -d "/dev/dri" ] && [ -n "$(ls -A /dev/dri/ 2>/dev/null)" ]; then
        echo "✅ Intel/AMD GPU devices detected (DRI)"
        ls -la /dev/dri/ | head -5
        # Set permissions for GPU access
        if [ -e "/dev/dri/renderD128" ]; then
            chmod 666 /dev/dri/renderD128 2>/dev/null || echo "⚠️ Could not set permissions for renderD128"
        fi
        if [ -e "/dev/dri/card0" ]; then
            chmod 666 /dev/dri/card0 2>/dev/null || echo "⚠️ Could not set permissions for card0"
        fi
        GPU_DETECTED="true"
        GPU_TYPE="Intel/AMD"
        export ENABLE_GPU_ACCELERATION=true
        export GPU_BACKEND_TYPE=vaapi
    # Check for AMD ROCm
    elif [ -e "/dev/kfd" ]; then
        echo "✅ AMD ROCm device detected (/dev/kfd)"
        ls -la /dev/kfd
        chmod 666 /dev/kfd 2>/dev/null || echo "⚠️ Could not set permissions for KFD"
        GPU_DETECTED="true"
        GPU_TYPE="AMD ROCm"
        export ENABLE_GPU_ACCELERATION=true
        export GPU_BACKEND_TYPE=vaapi
    # Manual override
    elif [ "${ENABLE_GPU_ACCELERATION:-false}" = "true" ]; then
        echo "🚀 GPU acceleration explicitly enabled via environment variable"
        GPU_DETECTED="true"
        GPU_TYPE="Manual"
    else
        echo "❌ No GPU devices detected - using CPU-only processing"
        echo ""
        echo "💡 To enable GPU acceleration, add one of the following to your docker run/compose:"
        echo "   NVIDIA: --gpus all  (requires NVIDIA Container Toolkit)"
        echo "   Intel:  --device=/dev/dri:/dev/dri --group-add video"
        echo "   AMD:    --device=/dev/dri:/dev/dri --device=/dev/kfd:/dev/kfd --group-add video"
    fi

    if [ "$GPU_DETECTED" = "true" ]; then
        echo "🎮 GPU Type: $GPU_TYPE"
        echo "🎯 Backend: $GPU_BACKEND_TYPE"
        echo "✅ GPU passthrough configured successfully"
    fi

else
    echo "🖥️ Running on host system (not in container)"
    echo "🎯 Hardware acceleration will be auto-detected by Python backend"
fi

echo ""
echo "🏁 Starting services..."
echo "======================"

# Set environment variables for hardware acceleration
export LIBVA_DRIVER_NAME=${LIBVA_DRIVER_NAME:-iHD}  # Intel default, can be overridden
export VAAPI_DEVICE=${VAAPI_DEVICE:-/dev/dri/renderD128}

# Start supervisor to manage both nginx and FastAPI
echo "🔧 Starting supervisor with nginx and FastAPI..."
exec supervisord -c /etc/supervisor/conf.d/supervisord.conf -n