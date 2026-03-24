# Docker API Reference (for `freq media` interactive)

> Extracted from CLAUDE.md for on-demand reference. Production fleet APIs.

### Sonarr (VM 102)
```
Base URL: http://10.25.255.31:8989
Auth: X-Api-Key header (key in /opt/dc01/configs/sonarr/config.xml — <ApiKey>)
  GET /api/v3/health          — health alerts
  GET /api/v3/series          — all shows
  GET /api/v3/queue           — download queue
  GET /api/v3/calendar        — upcoming episodes
  GET /api/v3/system/status   — system info
  POST /api/v3/command        — trigger actions
```

### Radarr (VM 102)
```
Base URL: http://10.25.255.31:7878
Auth: X-Api-Key header (key in /opt/dc01/configs/radarr/config.xml — <ApiKey>)
  GET /api/v3/health          — health alerts
  GET /api/v3/movie           — all movies
  GET /api/v3/queue           — download queue
  GET /api/v3/system/status   — system info
  POST /api/v3/command        — trigger actions
```

### Prowlarr (VM 102) — SOURCE OF TRUTH for indexers
```
Base URL: http://10.25.255.31:9696
Auth: X-Api-Key header (key in /opt/dc01/configs/prowlarr/config.xml — <ApiKey>)
  GET /api/v1/health          — health alerts
  GET /api/v1/indexer         — all indexers
  GET /api/v1/indexerstats    — indexer performance
  GET /api/v1/system/status   — system info
```

### Bazarr (VM 102)
```
Base URL: http://10.25.255.31:6767
Auth: X-Api-Key header (key in /opt/dc01/configs/bazarr/config/config.ini — [auth] apikey)
  GET /api/series             — TV with subtitle status
  GET /api/movies             — movies with subtitle status
  GET /api/system/status      — system info
```

### Overseerr (VM 102)
```
Base URL: http://10.25.255.31:5055
Auth: X-Api-Key header (key in /opt/dc01/configs/overseerr/settings.json — main.apiKey)
  GET /api/v1/request         — all requests
  GET /api/v1/status          — system status
  GET /api/v1/media           — media items
```

### Tautulli (VM 102)
```
Base URL: http://10.25.255.31:8181
Auth: apikey query parameter (key in /opt/dc01/configs/tautulli/config.ini — api_key)
  GET /api/v2?apikey=KEY&cmd=get_activity    — active streams
  GET /api/v2?apikey=KEY&cmd=get_libraries   — library stats
  GET /api/v2?apikey=KEY&cmd=get_history     — play history
```

### Plex (VM 101)
```
Base URL: http://10.25.255.30:32400
Auth: X-Plex-Token header
  GET /status/sessions        — active streams
  GET /library/sections       — all libraries
  GET /library/sections/1/all — all movies
  GET /library/sections/2/all — all shows
```

### qBittorrent (VM 103 + VM 202)
```
Base URLs: http://10.25.255.32:8080, http://10.25.255.35:8080
Auth: POST /api/v2/auth/login (session cookie)
  GET /api/v2/app/version         — app version
  GET /api/v2/transfer/info       — transfer stats
  GET /api/v2/torrents/info       — all torrents
  POST /api/v2/torrents/pause     — pause torrent
  POST /api/v2/torrents/resume    — resume torrent
```

### SABnzbd (VM 201)
```
Base URL: http://10.25.255.150:8080
Auth: apikey query parameter
  GET /api?mode=queue&apikey=KEY&output=json     — download queue
  GET /api?mode=history&apikey=KEY&output=json    — history
  GET /api?mode=server_stats&apikey=KEY&output=json — server stats
  GET /api?mode=version&apikey=KEY&output=json    — version
```

### Tdarr (VM 104 server, VM 301 worker)
```
Base URL: http://10.25.255.33:8265
Auth: x-api-key header
  POST /api/v2/cruddb         — database queries (file stats, library stats)
  GET  /api/v2/get-nodes      — worker node status
```

### Gluetun (VM 103, VM 202)
```
Port: 8000 (internal only)
  GET /v1/openvpn/status      — VPN status
  GET /v1/publicip/ip         — current public IP
```
