#!/bin/bash
# Fix ownership of mounted volumes, then drop to non-root user
chown -R claude:claude /data /work /home/claude/.claude 2>/dev/null || true
exec gosu claude python3 main.py
