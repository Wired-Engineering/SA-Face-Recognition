#!/bin/bash
set -e

# Create required directories
mkdir -p /var/log/supervisor /var/log/nginx

# Start supervisor to manage both nginx and FastAPI
exec supervisord -c /etc/supervisor/conf.d/supervisord.conf -n