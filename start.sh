#!/bin/bash
# start.sh — Pull latest code, rebuild if needed, and start the container.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "[$(date)] Pulling latest from git..."
git fetch origin main
git reset --hard origin/main

echo "[$(date)] Building Docker image (will use cache if unchanged)..."
docker compose build

echo "[$(date)] Starting container..."
docker compose up -d

echo "[$(date)] Claude Task Runner started."
