#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

VENV="$HOME/virtual_envs/inat-uploader"
PORT=5000

echo "Starting iNat Batch Uploader (web)"

# Start Flask in background
"$VENV/bin/python" web_app.py &
FLASK_PID=$!
echo "Flask PID: $FLASK_PID"

# Give Flask a moment to bind
sleep 1

# Open Cloudflare tunnel (prints the public URL)
echo ""
echo "Public URL (Cloudflare tunnel):"
cloudflared tunnel --url "http://localhost:$PORT" &
TUNNEL_PID=$!

# Cleanup on exit
trap "kill $FLASK_PID $TUNNEL_PID 2>/dev/null; echo Stopped." EXIT INT TERM

wait $FLASK_PID
