#!/bin/sh
set -e
mkdir -p /home/freqtest/.ssh
[ -n "$AUTHORIZED_KEY" ] && printf '%s\n' "$AUTHORIZED_KEY" > /home/freqtest/.ssh/authorized_keys
chown -R freqtest:freqtest /home/freqtest/.ssh; chmod 700 /home/freqtest/.ssh; chmod 600 /home/freqtest/.ssh/authorized_keys 2>/dev/null || true
ssh-keygen -A >/dev/null 2>&1   # fresh host keys each start
exec /usr/sbin/sshd -D -e
