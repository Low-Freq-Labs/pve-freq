FROM python:3.13-slim-bookworm

LABEL maintainer="LOW FREQ Labs"
LABEL description="PVE FREQ — Datacenter management CLI"

# Install system deps (ssh client, sshpass for fleet ops)
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        openssh-client sshpass curl jq && \
    rm -rf /var/lib/apt/lists/*

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

USER freq
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["serve"]
