#!/usr/bin/env bash
# Activate the inat-uploader virtual environment and run the uploader.
# Usage: ./run.sh /path/to/photos [any upload_observations.py options]
#
# Example:
#   ./run.sh ~/trip_photos --dry-run
#   ./run.sh ~/trip_photos --location "Bukit Timah, Singapore" -t butterflies

VENV_DIR="${VENV_DIR:-$HOME/virtual_envs/inat-uploader}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -f "$VENV_DIR/bin/activate" ]; then
    echo "Virtual environment not found at $VENV_DIR"
    echo "Run ./setup.sh first to create it."
    exit 1
fi

source "$VENV_DIR/bin/activate"

# Auto-reinstall if requirements.txt changed since last install
MARKER="$VENV_DIR/.last_install"
if [ ! -f "$MARKER" ] || [ "$SCRIPT_DIR/requirements.txt" -nt "$MARKER" ]; then
    echo "Installing/updating dependencies..."
    pip install -q -r "$SCRIPT_DIR/requirements.txt" && touch "$MARKER"
fi

python3 "$SCRIPT_DIR/upload_observations.py" "$@"
