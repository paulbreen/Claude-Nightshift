FROM node:20-slim

# ─── System Dependencies ────────────────────────────────────────────────
RUN apt-get update && apt-get install -y \
    git \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    jq \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# ─── Claude CLI ──────────────────────────────────────────────────────────
RUN npm install -g @anthropic-ai/claude-code

# ─── Python App ──────────────────────────────────────────────────────────
WORKDIR /app
COPY requirements.txt .
RUN pip install --break-system-packages -r requirements.txt

COPY . .

# ─── Non-root User ──────────────────────────────────────────────────────
RUN useradd -m -s /bin/bash claude

# ─── Directories ─────────────────────────────────────────────────────────
RUN mkdir -p /data /work/repos /work/worktrees && \
    chown -R claude:claude /data /work /app

# ─── Git Config (as claude user) ────────────────────────────────────────
RUN gosu claude git config --global user.name "Claude Worker" && \
    gosu claude git config --global user.email "claude-worker@noreply.github.com" && \
    gosu claude git config --global --add safe.directory "*"

# ─── Environment ─────────────────────────────────────────────────────────
ENV DATA_DIR=/data
ENV WORK_DIR=/work
ENV PYTHONUNBUFFERED=1

# ─── Volumes ─────────────────────────────────────────────────────────────
VOLUME ["/data"]

# ─── Entrypoint ──────────────────────────────────────────────────────────
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
