FROM node:20-slim

# ─── System Dependencies ────────────────────────────────────────────────
RUN apt-get update && apt-get install -y \
    git \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    jq \
    && rm -rf /var/lib/apt/lists/*

# ─── Claude CLI ──────────────────────────────────────────────────────────
RUN npm install -g @anthropic-ai/claude-code

# ─── Python App ──────────────────────────────────────────────────────────
WORKDIR /app
COPY requirements.txt .
RUN pip install --break-system-packages -r requirements.txt

COPY . .

# ─── Git Config ──────────────────────────────────────────────────────────
RUN git config --global user.name "Claude Worker" && \
    git config --global user.email "claude-worker@noreply.github.com" && \
    git config --global --add safe.directory "*"

# ─── Directories ─────────────────────────────────────────────────────────
RUN mkdir -p /data /work/repos /work/worktrees

# ─── Environment ─────────────────────────────────────────────────────────
ENV DATA_DIR=/data
ENV WORK_DIR=/work
ENV PYTHONUNBUFFERED=1

# ─── Volumes ─────────────────────────────────────────────────────────────
VOLUME ["/data"]

# ─── Entrypoint ──────────────────────────────────────────────────────────
CMD ["python3", "main.py"]
