# syntax=docker/dockerfile:1
# ──────────────────────────────────────────────────────────────────
# PVE FREQ — Docker Image (in-repo build)
# Fleet management CLI, TUI, and dashboard for Proxmox VE
# ──────────────────────────────────────────────────────────────────
FROM python:3.13.5-slim-bookworm

LABEL maintainer="LOW FREQ Labs"
LABEL description="PVE FREQ — Datacenter management CLI"
LABEL org.opencontainers.image.source="https://github.com/Low-Freq-Labs/pve-freq"

# System deps — single layer, cleanup included
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        openssh-client sshpass curl jq tini && \
    rm -rf /var/lib/apt/lists/*

# Generate machine-id (needed for vault key derivation)
RUN [ -f /etc/machine-id ] || python3 -c "import uuid; print(uuid.uuid4().hex)" > /etc/machine-id \
    && chmod 444 /etc/machine-id

# Create non-root user with known UID/GID
RUN groupadd --gid 1000 freq \
    && useradd --uid 1000 --gid freq --shell /bin/bash --create-home freq \
    && mkdir -p /opt/pve-freq/conf /opt/pve-freq/data/log \
               /opt/pve-freq/data/vault /opt/pve-freq/data/keys \
               /opt/pve-freq/data/cache /opt/pve-freq/data/knowledge \
    && chown -R freq:freq /opt/pve-freq

WORKDIR /opt/pve-freq

# Copy source — root-owned so runtime user cannot modify application code
COPY freq/ freq/
COPY pyproject.toml .
COPY install.sh .
COPY README.md LICENSE CHANGELOG.md ./

# Install FREQ
RUN pip install --no-deps --no-cache-dir --break-system-packages . && \
    freq --version

# Copy entrypoint — root-owned, executable
COPY --chmod=755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Runtime environment
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FREQ_PORT=8888

# Dashboard port
EXPOSE 8888

# Health check — start-period gives the app time to boot
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=15s \
    CMD curl -sf http://localhost:8888/healthz || exit 1

# Drop to non-root user
USER freq

# tini handles PID 1 signal forwarding and zombie reaping
ENTRYPOINT ["tini", "--", "docker-entrypoint.sh"]
CMD ["serve"]
