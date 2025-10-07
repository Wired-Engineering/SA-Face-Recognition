# Global ARG for device type selection (must be before any FROM)
ARG DEVICE=cpu

# Build stage
FROM node:23-alpine AS build

ENV PNPM_HOME="/pnpm"
ENV PATH="$PNPM_HOME:$PATH"

WORKDIR /app

# Copy package files
COPY pnpm-lock.yaml package.json ./

RUN corepack enable
RUN pnpm install --frozen-lockfile

# Copy source and build (with cache busting)
COPY . .
RUN rm -rf dist node_modules/.cache .vite
RUN pnpm build

# ============================================================================
# Builder stages - prepare dependencies for each device type
# ============================================================================

# Base Ubuntu 24.04 builder with Python 3.12
FROM ubuntu:24.04 AS builder-base

# Install Python 3.12 (native to Ubuntu 24.04)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
    python3-pip \
    && ln -sf /usr/bin/python3.12 /usr/bin/python3 \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

# CPU builder - extends base
FROM builder-base AS builder-cpu

# CUDA builder - extends base
FROM builder-base AS builder-cuda

# OpenVINO builder - extends base
FROM builder-base AS builder-openvino

# ROCm builder - use ROCm complete base image
FROM rocm/dev-ubuntu-24.04:7.0-complete AS builder-rocm

# Install Python 3.12 (native to Ubuntu 24.04)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
    python3-pip \
    && ln -sf /usr/bin/python3.12 /usr/bin/python3 \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

# Set ROCm environment variables
ENV ROCM_HOME=/opt/rocm \
    LD_LIBRARY_PATH=/opt/rocm/lib:${LD_LIBRARY_PATH} \
    PATH=/opt/rocm/bin:${PATH}

# Select appropriate builder based on DEVICE arg
FROM builder-${DEVICE} AS builder

ARG DEVICE

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

# Create virtual environment
RUN python3 -m venv /opt/venv

# Install Python dependencies based on device type
WORKDIR /tmp
COPY src/python/requirements-base.txt ./
COPY src/python/requirements-cpu.txt ./
COPY src/python/requirements-cuda.txt ./
COPY src/python/requirements-openvino.txt ./
COPY src/python/requirements-rocm.txt ./

RUN pip3 install --no-cache-dir --upgrade pip && \
    pip3 install --no-cache-dir -r requirements-${DEVICE}.txt

# ============================================================================
# Production stages - minimal runtime images for each device type
# ============================================================================

# Base production stage with Python 3.12
FROM ubuntu:24.04 AS prod-base

# Install Python 3.12 (native to Ubuntu 24.04)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
    python3-pip \
    && ln -sf /usr/bin/python3.12 /usr/bin/python3 \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

# CPU production - extends base
FROM prod-base AS prod-cpu

# CUDA production - NVIDIA CUDA runtime (Ubuntu 24.04)
# Note: cudnn-runtime base already includes libcudnn9-cuda-12
FROM nvidia/cuda:12.9.1-cudnn-runtime-ubuntu24.04 AS prod-cuda

# Install Python 3.12 (native to Ubuntu 24.04)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
    python3-pip \
    && ln -sf /usr/bin/python3.12 /usr/bin/python3 \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

# OpenVINO production - extends base + Intel OpenCL runtime
FROM prod-base AS prod-openvino

# Install Intel OpenCL runtime
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ocl-icd-libopencl1 \
    wget \
    && wget -nv https://github.com/intel/intel-graphics-compiler/releases/download/igc-1.0.17384.11/intel-igc-core_1.0.17384.11_amd64.deb \
    && wget -nv https://github.com/intel/intel-graphics-compiler/releases/download/igc-1.0.17384.11/intel-igc-opencl_1.0.17384.11_amd64.deb \
    && wget -nv https://github.com/intel/compute-runtime/releases/download/24.31.30508.7/intel-opencl-icd_24.31.30508.7_amd64.deb \
    && wget -nv https://github.com/intel/compute-runtime/releases/download/24.31.30508.7/libigdgmm12_22.4.1_amd64.deb \
    && dpkg -i *.deb \
    && rm *.deb \
    && apt-get remove wget -yqq \
    && rm -rf /var/lib/apt/lists/*

# ROCm production - ROCm complete dev image (includes all runtime libraries)
FROM rocm/dev-ubuntu-24.04:7.0-complete AS prod-rocm

# Install Python 3.12
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
    python3-pip \
    && ln -sf /usr/bin/python3.12 /usr/bin/python3 \
    && ln -sf /usr/bin/python3 /usr/bin/python \
    && rm -rf /var/lib/apt/lists/*

# Set ROCm environment variables
ENV ROCM_HOME=/opt/rocm \
    LD_LIBRARY_PATH=/opt/rocm/lib:${LD_LIBRARY_PATH} \
    PATH=/opt/rocm/bin:${PATH}

# ============================================================================
# Final production stage - select based on DEVICE arg
# ============================================================================

FROM prod-${DEVICE} AS prod

ARG DEVICE

# Install common system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    nginx \
    supervisor \
    openssl \
    curl \
    # Minimal OpenCV dependencies
    libgl1 \
    libglib2.0-0 \
    libx11-6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Set environment to use virtual environment
# Preserve ROCm library paths if using ROCm device
ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LD_LIBRARY_PATH="/opt/rocm/lib:${LD_LIBRARY_PATH}" \
    ROCM_HOME=/opt/rocm

# Copy Python source code
COPY src/python/ ./src/python/

# Copy migration scripts
COPY migrate_schema.py migrate_data_to_postgres.py ./

# Copy built frontend files to nginx
COPY --from=build /app/dist /var/www/html

# Copy nginx configuration
COPY nginx.conf /etc/nginx/nginx.conf

# Generate self-signed SSL certificate for testing (works with any IP/domain)
RUN mkdir -p /etc/nginx/ssl && \
    openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /etc/nginx/ssl/nginx.key \
    -out /etc/nginx/ssl/nginx.crt \
    -subj "/C=US/ST=Florida/L=Orlando/O=Wired Engineering/CN=*" \
    -addext "subjectAltName=DNS:localhost,DNS:*.local,IP:0.0.0.0" && \
    chmod 644 /etc/nginx/ssl/nginx.crt && \
    chmod 600 /etc/nginx/ssl/nginx.key && \
    chown -R www-data:www-data /etc/nginx/ssl

# Create directories and set permissions
RUN mkdir -p /app/src/python/system \
             /app/src/python/images \
             /var/log/supervisor \
    && chown -R www-data:www-data /app/src/python \
    && chown -R www-data:www-data /var/www/html

# Copy entrypoint script
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Create supervisor configuration
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

VOLUME ["/app/src/python/system", "/app/src/python/images", "/app/src/python/weights"]

EXPOSE 443

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=40s \
    CMD curl -f -k https://localhost:443/api/system/health || exit 1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
