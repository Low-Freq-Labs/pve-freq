Title: TrueNAS REST API deprecation — removal in version 26.04
Session: S027-20260220
Context: Audit Phase A — TrueNAS alert shows "The deprecated REST API was used to authenticate 2 times in the last 24 hours from ::1". TrueNAS 26.04 will remove REST API entirely.
Diagnosis: Something on TrueNAS (likely internal middleware) is using the deprecated REST API. When TrueNAS is upgraded to 26.04, this will break. Current version is 25.10.1. [CONFIRMED]
Exact Fix: (1) Identify what is making REST API calls from localhost (::1). (2) Before upgrading to 26.04, migrate integrations to JSON-RPC 2.0 over WebSocket. (3) No immediate action needed — 26.04 is a future release.
Priority: P4
