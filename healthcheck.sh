#!/usr/bin/env bash
# healthcheck.sh — manage the iNat Batch Uploader web app + Cloudflare tunnel
#
# Usage:
#   ./healthcheck.sh           show status of Flask and tunnel
#   ./healthcheck.sh --fix     restart only broken/stalled services
#   ./healthcheck.sh --restart stop and restart everything

cd "$(dirname "$0")"

VENV="$HOME/virtual_envs/inat-uploader"
PORT=5000
FLASK_LOG=/tmp/flask.log
TUNNEL_LOG=/tmp/cf_tunnel.log

# ── helpers ──────────────────────────────────────────────────────────────────

green()  { printf '\033[32m%s\033[0m\n' "$*"; }
red()    { printf '\033[31m%s\033[0m\n' "$*"; }
yellow() { printf '\033[33m%s\033[0m\n' "$*"; }
bold()   { printf '\033[1m%s\033[0m\n' "$*"; }

flask_pid()  { pgrep -f web_app.py    2>/dev/null | head -1 || true; }
tunnel_pid() { pgrep -f "cloudflared tunnel" 2>/dev/null | head -1 || true; }
tunnel_url() { grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$TUNNEL_LOG" 2>/dev/null | tail -1 || true; }
flask_ok()   { curl -sf --max-time 3 "http://localhost:$PORT/" > /dev/null 2>&1; }

# ── status ────────────────────────────────────────────────────────────────────

show_status() {
    bold "=== iNat Uploader Status ==="
    echo ""

    local fpid; fpid=$(flask_pid)
    if [ -n "$fpid" ]; then
        if flask_ok; then
            green "  Flask      running  (PID $fpid, responding on :$PORT)"
        else
            yellow "  Flask      stalled  (PID $fpid, not responding) — try --fix"
        fi
    else
        red "  Flask      stopped"
    fi

    local tpid; tpid=$(tunnel_pid)
    local url;  url=$(tunnel_url)
    if [ -n "$tpid" ]; then
        if [ -n "$url" ]; then
            green "  Tunnel     running  (PID $tpid)"
            green "  Public URL $url"
        else
            yellow "  Tunnel     starting (PID $tpid, URL not yet available)"
        fi
    else
        red "  Tunnel     stopped"
        [ -n "$url" ] && yellow "  Last URL   $url  (stale)"
    fi

    echo ""
    echo "  Flask log:  $FLASK_LOG"
    echo "  Tunnel log: $TUNNEL_LOG"
}

# ── start/stop helpers ────────────────────────────────────────────────────────

start_flask() {
    echo "Starting Flask..."
    nohup "$VENV/bin/python" web_app.py >> "$FLASK_LOG" 2>&1 &
    sleep 2
    local fpid; fpid=$(flask_pid)
    if [ -n "$fpid" ]; then
        green "Flask started (PID $fpid)"
    else
        red "Flask failed to start — check $FLASK_LOG"
        return 1
    fi
}

start_tunnel() {
    > "$TUNNEL_LOG"
    echo "Starting Cloudflare tunnel..."
    nohup cloudflared tunnel --url "http://localhost:$PORT" >> "$TUNNEL_LOG" 2>&1 &
    echo "Waiting for public URL..."
    for _ in $(seq 1 20); do
        local url; url=$(tunnel_url)
        if [ -n "$url" ]; then
            green "Tunnel URL: $url"
            return 0
        fi
        sleep 1
    done
    yellow "Tunnel started but URL not yet visible — check $TUNNEL_LOG"
}

stop_flask() {
    local fpid; fpid=$(flask_pid)
    if [ -n "$fpid" ]; then
        echo "Stopping Flask (PID $fpid)..."
        kill "$fpid" 2>/dev/null
        sleep 1
    fi
}

stop_tunnel() {
    local tpid; tpid=$(tunnel_pid)
    if [ -n "$tpid" ]; then
        echo "Stopping tunnel (PID $tpid)..."
        kill "$tpid" 2>/dev/null
        sleep 1
    fi
}

# ── fix ───────────────────────────────────────────────────────────────────────

do_fix() {
    bold "=== Fixing stalled processes ==="
    echo ""

    local fpid; fpid=$(flask_pid)
    if [ -n "$fpid" ] && ! flask_ok; then
        yellow "Flask is stalled — restarting..."
        stop_flask && start_flask
    elif [ -z "$fpid" ]; then
        yellow "Flask is not running — starting..."
        start_flask
    else
        green "Flask is healthy, no fix needed."
    fi

    echo ""

    local tpid; tpid=$(tunnel_pid)
    local url;  url=$(tunnel_url)
    if [ -z "$tpid" ]; then
        yellow "Tunnel is not running — starting..."
        start_tunnel
    elif [ -z "$url" ]; then
        yellow "Tunnel has no URL — restarting..."
        stop_tunnel && start_tunnel
    else
        green "Tunnel is healthy ($url), no fix needed."
    fi
}

# ── restart ───────────────────────────────────────────────────────────────────

do_restart() {
    bold "=== Restarting app and tunnel ==="
    echo ""
    stop_flask
    stop_tunnel
    start_flask
    echo ""
    start_tunnel
}

# ── main ──────────────────────────────────────────────────────────────────────

case "${1:-}" in
    --fix)     do_fix     ;;
    --restart) do_restart ;;
    "")        show_status ;;
    *)
        echo "Usage: $0 [--fix | --restart]"
        echo "  (no args)   show status of Flask and tunnel"
        echo "  --fix       restart only broken/stalled services"
        echo "  --restart   stop and restart everything"
        exit 1
        ;;
esac
