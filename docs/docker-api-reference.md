# Docker Container API Reference

> Reference for common Docker container APIs managed by FREQ's media stack.
> Replace IPs and ports with your actual deployment values.

### Sonarr
```
Base URL: http://<docker-host>:8989
Auth: X-Api-Key header (from config.xml — <ApiKey>)
  GET /api/v3/health          — health alerts
  GET /api/v3/series          — all shows
  GET /api/v3/queue           — download queue
  GET /api/v3/calendar        — upcoming episodes
  GET /api/v3/system/status   — system info
  POST /api/v3/command        — trigger actions
```

### Radarr
```
Base URL: http://<docker-host>:7878
Auth: X-Api-Key header (from config.xml — <ApiKey>)
  GET /api/v3/health          — health alerts
  GET /api/v3/movie           — all movies
  GET /api/v3/queue           — download queue
  GET /api/v3/system/status   — system info
  POST /api/v3/command        — trigger actions
```

### Prowlarr — Indexer source of truth
```
Base URL: http://<docker-host>:9696
Auth: X-Api-Key header (from config.xml — <ApiKey>)
  GET /api/v1/health          — health alerts
  GET /api/v1/indexer         — all indexers
  GET /api/v1/indexerstats    — indexer performance
  GET /api/v1/system/status   — system info
```

### Bazarr
```
Base URL: http://<docker-host>:6767
Auth: X-Api-Key header (from config.ini — [auth] apikey)
  GET /api/series             — TV with subtitle status
  GET /api/movies             — movies with subtitle status
  GET /api/system/status      — system info
```

### Overseerr
```
Base URL: http://<docker-host>:5055
Auth: X-Api-Key header (from settings.json — main.apiKey)
  GET /api/v1/request         — all requests
  GET /api/v1/status          — system status
  GET /api/v1/media           — media items
```

### Tautulli
```
Base URL: http://<docker-host>:8181
Auth: apikey query parameter (from config.ini — api_key)
  GET /api/v2?apikey=KEY&cmd=get_activity    — active streams
  GET /api/v2?apikey=KEY&cmd=get_libraries   — library stats
  GET /api/v2?apikey=KEY&cmd=get_history     — play history
```

### Plex
```
Base URL: http://<plex-host>:32400
Auth: X-Plex-Token header
  GET /status/sessions        — active streams
  GET /library/sections       — all libraries
  GET /library/sections/1/all — all movies
  GET /library/sections/2/all — all shows
```

### qBittorrent
```
Base URL: http://<docker-host>:8080
Auth: POST /api/v2/auth/login (session cookie)
  GET /api/v2/app/version         — app version
  GET /api/v2/transfer/info       — transfer stats
  GET /api/v2/torrents/info       — all torrents
  POST /api/v2/torrents/pause     — pause torrent
  POST /api/v2/torrents/resume    — resume torrent
```

### SABnzbd
```
Base URL: http://<docker-host>:8080
Auth: apikey query parameter
  GET /api?mode=queue&apikey=KEY&output=json     — download queue
  GET /api?mode=history&apikey=KEY&output=json    — history
  GET /api?mode=server_stats&apikey=KEY&output=json — server stats
  GET /api?mode=version&apikey=KEY&output=json    — version
```

### Tdarr
```
Base URL: http://<docker-host>:8265
Auth: x-api-key header
  POST /api/v2/cruddb         — database queries (file stats, library stats)
  GET  /api/v2/get-nodes      — worker node status
```

### Gluetun (VPN container)
```
Port: 8000 (internal only — services route through gluetun's network)
  GET /v1/openvpn/status      — VPN status
  GET /v1/publicip/ip         — current public IP
```
