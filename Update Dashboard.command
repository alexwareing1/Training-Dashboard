#!/bin/bash
#
# Update Dashboard
# Double-click to fetch new workouts, rebuild the dashboard, and open it.
#

# Always run from the folder this script lives in.
cd "$(dirname "$0")" || exit 1

VENV_PYTHON=".venv/bin/python"

if [ ! -x "$VENV_PYTHON" ]; then
    echo "Could not find the virtualenv Python at $VENV_PYTHON"
    echo "Press any key to close."
    read -n 1 -s
    exit 1
fi

echo ""
echo "==> Fetching new workouts..."
"$VENV_PYTHON" sync-hevy.py || { echo "sync-hevy.py failed."; echo "Press any key to close."; read -n 1 -s; exit 1; }

echo ""
echo "==> Rebuilding the dashboard..."
"$VENV_PYTHON" rebuild-dashboard.py || { echo "rebuild-dashboard.py failed."; echo "Press any key to close."; read -n 1 -s; exit 1; }

echo ""
echo "==> Copying to iCloud Drive..."
ICLOUD_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs"
if mkdir -p "$ICLOUD_DIR" && cp index.html "$ICLOUD_DIR/index.html"; then
    echo "Copied index.html to iCloud Drive - it will sync to your phone."
else
    echo "Could not copy to iCloud Drive at $ICLOUD_DIR"
fi

echo ""
echo "==> Opening index.html..."
open index.html

echo ""
echo "Done!"
