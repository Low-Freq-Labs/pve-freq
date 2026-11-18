#!/bin/bash
set -e

# Bootstrap config if not present
if [ ! -f /opt/pve-freq/conf/freq.toml ] && [ ! -f /opt/pve-freq/conf/freq.toml.example ]; then
    echo "First run — seeding configuration from package data..."
    freq doctor 2>/dev/null || true
fi

case "${1:-serve}" in
    serve)
        exec freq serve --port "${FREQ_PORT:-8888}"
        ;;
    init)
        shift
        exec freq init "$@"
        ;;
    shell)
        exec /bin/bash
        ;;
    *)
        exec freq "$@"
        ;;
esac
