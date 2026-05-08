#!/usr/bin/env bash
cd "$(dirname "$0")"

VENV="$HOME/virtual_envs/inat-uploader"

echo "Stopping existing Flask process..."
pkill -f web_app.py 2>/dev/null && sleep 1 || true

echo "Starting Flask..."
nohup "$VENV/bin/python" web_app.py >> /tmp/flask.log 2>&1 &
sleep 2

if pgrep -f web_app.py > /dev/null; then
    echo "Flask restarted OK (PID $(pgrep -f web_app.py))"
else
    echo "ERROR: Flask failed to start. Check /tmp/flask.log"
    exit 1
fi

# Show current tunnel URL if tunnel is running
CF_URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' /tmp/cf_tunnel.log 2>/dev/null | tail -1)
if [ -n "$CF_URL" ]; then
    echo "Tunnel URL: $CF_URL"
else
    echo "No tunnel running. Start one with: bash run_web.sh"
fi
