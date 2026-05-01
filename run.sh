#!/usr/bin/env bash
# Activate the project virtual environment and run the uploader.
# Usage: ./run.sh /path/to/photos [any upload_observations.py options]
#
# Example:
#   ./run.sh ~/trip_photos --dry-run
#   ./run.sh ~/trip_photos --location "Bukit Timah, Singapore" -t butterflies

VENV_DIR="${VENV_DIR:-$HOME/virtual_envs/butterfly-id}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "ERROR: Virtual environment not found at $VENV_DIR"
    echo "Create it with:"
    echo "  python3 -m venv $VENV_DIR"
    echo "  $VENV_DIR/bin/pip install -r $SCRIPT_DIR/requirements.txt"
    exit 1
fi

source "$VENV_DIR/bin/activate"

# Install/update dependencies if requirements.txt is newer than last install marker
MARKER="$VENV_DIR/.last_install"
if [ ! -f "$MARKER" ] || [ "$SCRIPT_DIR/requirements.txt" -nt "$MARKER" ]; then
    echo "Installing/updating dependencies..."
    pip install -q -r "$SCRIPT_DIR/requirements.txt" && touch "$MARKER"
fi

python3 "$SCRIPT_DIR/upload_observations.py" "$@"
