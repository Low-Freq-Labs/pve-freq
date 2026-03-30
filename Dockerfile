FROM python:3.13-slim

LABEL maintainer="LOW FREQ Labs"
LABEL description="PVE FREQ — Datacenter management CLI"

# Install system deps (ssh client, sshpass for fleet ops, tini for signal handling)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        openssh-client sshpass curl jq tini && \
    rm -rf /var/lib/apt/lists/*

# Generate machine-id (needed for vault key derivation)
RUN [ -f /etc/machine-id ] || python3 -c "import uuid; print(uuid.uuid4().hex)" > /etc/machine-id \
    && chmod 444 /etc/machine-id

# Create freq user and directories
RUN useradd -r -m -s /bin/bash freq && \
    mkdir -p /opt/pve-freq/conf /opt/pve-freq/data/log \
             /opt/pve-freq/data/vault /opt/pve-freq/data/keys \
             /opt/pve-freq/data/cache /opt/pve-freq/data/knowledge && \
    chown -R freq:freq /opt/pve-freq

WORKDIR /opt/pve-freq

# Copy source
COPY --chown=freq:freq freq/ freq/
COPY --chown=freq:freq pyproject.toml .
COPY --chown=freq:freq install.sh .
COPY --chown=freq:freq README.md LICENSE CHANGELOG.md ./

# Install FREQ
RUN pip install --no-deps --no-cache-dir --break-system-packages . && \
    freq --version

# Copy entrypoint
COPY --chown=freq:freq docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Volumes for persistent data
VOLUME ["/opt/pve-freq/conf", "/opt/pve-freq/data"]

# Dashboard port
EXPOSE 8888

# Health check for orchestrators
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -f http://localhost:8888/healthz || exit 1

USER freq
ENTRYPOINT ["tini", "--", "docker-entrypoint.sh"]
CMD ["serve"]
