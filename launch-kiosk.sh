#!/bin/bash

# Signature Aviation Face Recognition - Kiosk Mode Launcher
# This script launches the welcome popup in true kiosk mode

URL="http://localhost:5173/welcome-popup.html"

# Kill any existing Chrome instances in kiosk mode (optional)
# pkill -f "Google Chrome.*--kiosk"

# Launch Chrome in kiosk mode
# --kiosk: Full screen without chrome UI
# --app: Opens as an app window
# --disable-pinch: Prevents pinch-to-zoom
# --overscroll-history-navigation=0: Disables swipe navigation
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
    --kiosk \
    --app="$URL" \
    --disable-pinch \
    --overscroll-history-navigation=0 \
    --noerrdialogs \
    --disable-infobars \
    --check-for-update-interval=604800 \
    --disable-session-crashed-bubble