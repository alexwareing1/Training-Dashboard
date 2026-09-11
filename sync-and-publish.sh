#!/bin/bash
#
# sync-and-publish.sh
# Pulls new Hevy workouts, rebuilds the dashboard, and pushes the result to
# GitHub. Run hourly by the com.alexwareing.training-dashboard.sync launchd
# agent (see com.alexwareing.training-dashboard.sync.plist). Safe to run by
# hand too.
#
set -uo pipefail

cd "$(dirname "$0")" || exit 1

VENV_PYTHON=".venv/bin/python"

echo ""
echo "===== $(date '+%Y-%m-%d %H:%M:%S') : starting pipeline ====="

if [ ! -x "$VENV_PYTHON" ]; then
    echo "Could not find the virtualenv Python at $VENV_PYTHON"
    exit 1
fi

echo "==> Fetching new workouts..."
"$VENV_PYTHON" sync-hevy.py
status=$?
if [ $status -ne 0 ]; then
    echo "sync-hevy.py failed with exit code $status"
    exit 1
fi

echo "==> Rebuilding the dashboard..."
"$VENV_PYTHON" rebuild-dashboard.py
status=$?
if [ $status -ne 0 ]; then
    echo "rebuild-dashboard.py failed with exit code $status"
    exit 1
fi

echo "==> Checking for changes to publish..."
if [ -n "$(git status --porcelain -- index.html)" ]; then
    git add index.html
    git commit -m "Automated sync $(date '+%Y-%m-%d %H:%M')"
    status=$?
    if [ $status -ne 0 ]; then
        echo "git commit failed with exit code $status"
        exit 1
    fi

    git push origin main
    status=$?
    if [ $status -ne 0 ]; then
        echo "git push failed with exit code $status"
        exit 1
    fi
    echo "Committed and pushed index.html."
else
    echo "No changes to index.html - nothing to publish."
fi

echo "===== $(date '+%Y-%m-%d %H:%M:%S') : pipeline complete ====="
