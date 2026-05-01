#!/usr/bin/env bash
# Create the inat-uploader virtual environment and install all dependencies.
# Run this once before using run.sh.

set -e

VENV_DIR="${VENV_DIR:-$HOME/virtual_envs/inat-uploader}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Creating virtual environment at $VENV_DIR ..."
mkdir -p "$(dirname "$VENV_DIR")"
python3 -m venv "$VENV_DIR"

echo "Upgrading pip..."
"$VENV_DIR/bin/pip" install --upgrade pip -q

echo "Installing dependencies..."
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt"

touch "$VENV_DIR/.last_install"

echo ""
echo "Setup complete. To run the uploader:"
echo "  ./run.sh /path/to/photos --dry-run"
