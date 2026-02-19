#!/bin/bash
# start.sh — Pull latest code, rebuild if needed, and start the container.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "[$(date)] Pulling latest from git..."
# Preserve user config across git reset
[ -f config.yaml ] && cp config.yaml config.yaml.bak
git fetch origin main
git reset --hard origin/main
[ -f config.yaml.bak ] && mv config.yaml.bak config.yaml

# Ensure config.yaml exists (gitignored, user-specific)
if [ ! -f config.yaml ]; then
    echo "[$(date)] No config.yaml found, copying from example..."
    cp config.yaml.example config.yaml
    echo "[$(date)] WARNING: Edit config.yaml with your settings before running."
fi

echo "[$(date)] Building Docker image (will use cache if unchanged)..."
docker compose build

echo "[$(date)] Starting container..."
docker compose up -d

echo "[$(date)] Claude Task Runner started."
