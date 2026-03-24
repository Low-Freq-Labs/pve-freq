# Pre-Change Baseline — S033 TrueNAS F-021 + F-022

**Date:** 2026-02-20
**Target:** TrueNAS (10.25.255.25)
**Changes:** Disable IPv6 web listeners (F-021), restrict SSH to mgmt interface (F-022)

## Pre-Change State

### F-021: Web UI Binding
```
ui_address: ['10.25.255.25']
ui_v6address: ['::']
ui_port: 80
ui_httpsport: 443
```

### F-022: SSH Config
```
bindiface: []
tcpport: 22
passwordauth: true
```

## Planned Changes

### F-021 Fix
```
midclt call system.general.update '{"ui_v6address": []}'
```
Effect: Removes IPv6 web listeners from all interfaces. IPv4 binding to 10.25.255.25 unchanged.

### F-022 Fix
```
midclt call ssh.update '{"bindiface": ["eno4"]}'
```
Effect: Restricts SSH to eno4 (10.25.255.25, management VLAN) only. SSH via 10.25.0.25 or 10.25.25.25 will stop working.

## Rollback Commands
```
midclt call system.general.update '{"ui_v6address": ["::"]}'
midclt call ssh.update '{"bindiface": []}'
```
