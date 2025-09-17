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

# # Production stage with Python base
# FROM python:3.13-alpine
FROM python:3.13-slim

RUN apt-get update && apt-get install -y \
    nginx \
    supervisor \
    openssl \
    && rm -rf /var/lib/apt/lists/*
    
# # Install nginx and system dependencies
# RUN apk add --no-cache nginx supervisor build-base cmake linux-headers jpeg-dev

WORKDIR /app

# Copy Python requirements and install
COPY src/python/requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy Python source code
COPY src/python/ ./src/python/

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

VOLUME ["/app/src/python/system", "/app/src/python/images"]

EXPOSE 443

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]