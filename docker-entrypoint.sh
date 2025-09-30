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

# GPU Hardware Detection and Diagnostics
echo "🔍 GPU Hardware Detection:"
echo "=========================="

# Check if running in Docker
if [ -f /.dockerenv ] || [ -f /proc/1/cgroup ]; then
    echo "🐳 Running in Docker container"

    # Check for DRI devices (Intel/AMD GPU)
    if [ -d "/dev/dri" ]; then
        echo "✅ DRI devices found:"
        ls -la /dev/dri/ || echo "   (no devices in /dev/dri/)"

        # Set permissions for GPU access
        if [ -e "/dev/dri/renderD128" ]; then
            chmod 666 /dev/dri/renderD128 2>/dev/null || echo "⚠️ Could not set permissions for renderD128"
        fi
        if [ -e "/dev/dri/card0" ]; then
            chmod 666 /dev/dri/card0 2>/dev/null || echo "⚠️ Could not set permissions for card0"
        fi
    else
        echo "❌ No DRI devices found - GPU passthrough not configured"
        echo "💡 To enable Intel GPU: --device=/dev/dri:/dev/dri --group-add video"
        echo "💡 To enable AMD GPU:   --device=/dev/dri:/dev/dri --device=/dev/kfd:/dev/kfd --group-add video --group-add render"
    fi

    # Check for KFD device (AMD specific)
    if [ -e "/dev/kfd" ]; then
        echo "✅ KFD device found (AMD GPU support)"
        ls -la /dev/kfd
        chmod 666 /dev/kfd 2>/dev/null || echo "⚠️ Could not set permissions for KFD"
    else
        echo "ℹ️ KFD device not found (AMD-specific, not required for Intel)"
    fi

    # Test VAAPI and Intel QuickSync functionality
    echo ""
    echo "🎥 Hardware Video Acceleration Test:"
    echo "===================================="

    # Test Intel QuickSync availability
    echo "🔧 Intel QuickSync Video (QSV) Test:"
    echo "⚠️ Intel Media SDK packages not installed (minimal image)"

    # Test VAAPI functionality
    echo ""
    echo "📋 VAAPI Test:"
    echo "⚠️ vainfo command not available (minimal image)"
    echo "💡 GPU drivers must be installed on host system for device passthrough"

    echo ""
    echo "🧠 AI System Hardware Acceleration Test:"
    echo "======================================="
    cd /app/src/python

    # Auto-detect GPU acceleration based on device passthrough
    GPU_DETECTED="false"
    GPU_TYPE=""

    # Check for NVIDIA GPU
    if command -v nvidia-smi &> /dev/null; then
        echo "✅ NVIDIA GPU detected (via nvidia-smi)"
        GPU_DETECTED="true"
        GPU_TYPE="NVIDIA"
        export ENABLE_GPU_ACCELERATION=true
    elif [ -e "/dev/nvidia0" ] || [ -e "/dev/nvidiactl" ]; then
        echo "✅ NVIDIA GPU devices detected"
        GPU_DETECTED="true"
        GPU_TYPE="NVIDIA"
        export ENABLE_GPU_ACCELERATION=true
    # Check for Intel/AMD GPU (DRI devices)
    elif [ -d "/dev/dri" ] && [ -n "$(ls -A /dev/dri/ 2>/dev/null)" ]; then
        echo "✅ Intel/AMD GPU devices detected (DRI)"
        GPU_DETECTED="true"
        GPU_TYPE="Intel/AMD"
        export ENABLE_GPU_ACCELERATION=true
    # Check for AMD ROCm
    elif [ -e "/dev/kfd" ]; then
        echo "✅ AMD ROCm device detected"
        GPU_DETECTED="true"
        GPU_TYPE="AMD ROCm"
        export ENABLE_GPU_ACCELERATION=true
    # Manual override
    elif [ "${ENABLE_GPU_ACCELERATION:-false}" = "true" ]; then
        echo "🚀 GPU acceleration explicitly enabled via environment variable"
        GPU_DETECTED="true"
        GPU_TYPE="Manual"
    else
        echo "💻 No GPU devices detected - using CPU-only processing (production safe mode)"
        echo "💡 To enable GPU acceleration:"
        echo "   NVIDIA: Use --gpus all or --runtime=nvidia"
        echo "   Intel:  --device=/dev/dri:/dev/dri --group-add video"
        echo "   AMD:    --device=/dev/dri:/dev/dri --device=/dev/kfd:/dev/kfd --group-add video --group-add render"
    fi

    if [ "$GPU_DETECTED" = "true" ]; then
        echo "🎮 GPU Type: $GPU_TYPE"
    fi

    if [ "$GPU_DETECTED" = "true" ]; then
        echo "🔬 Testing hardware acceleration detection..."
        python3 -c "
import sys, os
sys.path.append('.')
try:
    from api import configure_hardware_acceleration
    backend = configure_hardware_acceleration()
    print(f'🎯 Selected backend: {backend}')
    if backend != 'cpu':
        print('🚀 Hardware acceleration ENABLED')
    else:
        print('💻 GPU detection failed - falling back to CPU processing')
except Exception as e:
    print(f'❌ Hardware acceleration test failed: {e}')
    print('💻 Falling back to CPU processing')
"
    else
        echo "🎯 Selected backend: cpu"
    fi

else
    echo "🖥️ Running on host system (not in container)"
    cd /app/src/python
    python3 -c "
import sys, os
sys.path.append('.')
try:
    from api import configure_hardware_acceleration
    backend = configure_hardware_acceleration()
    print(f'🎯 Selected backend: {backend}')
except Exception as e:
    print(f'❌ Hardware acceleration test failed: {e}')
"
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