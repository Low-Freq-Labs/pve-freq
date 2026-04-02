# Screenshot Capture Guide

Screenshots for the README and docs. Capture from the live fleet with a dark terminal.

## Required Screenshots (10)

| # | File | Command/View | Where Used |
|---|------|-------------|------------|
| 1 | `fleet-status.png` | `freq fleet status` | README hero, features |
| 2 | `vm-list.png` | `freq vm list` | Features section |
| 3 | `switch-vlans.png` | `freq net switch vlans` | Network features |
| 4 | `cert-inventory.png` | `freq cert scan --expiring 30` | Cert features |
| 5 | `comply-scan.png` | `freq secure comply scan` | Security features |
| 6 | `metrics-top.png` | `freq observe metrics top` | Observability features |
| 7 | `dashboard-login.png` | Dashboard login page | Dashboard section |
| 8 | `dashboard-home.png` | Dashboard fleet view | Dashboard section |
| 9 | `freq-help.png` | `freq help` | Architecture section |
| 10 | `event-deploy.png` | `freq event deploy` output | Event networking |

## Capture Rules

- Real data from the live fleet, not fake
- Dark terminal background, monospace font
- Crop to content — no desktop, no taskbar
- Save PNG to this directory AND `/mnt/nexus/ss/`
- Minimum 1200px wide for readability on GitHub

## Text Captures (already saved)

These ANSI text captures are saved for reference:
- `freq-help.txt` — Full `freq help` output
- `freq-version.txt` — Version/branding output
- `freq-doctor.txt` — Self-diagnostic output

## How to Capture

From a terminal on Nexus (or any host with fleet access):

```bash
# Terminal screenshots (use a tool like gnome-screenshot, scrot, or maim)
freq fleet status   # screenshot while output is visible
freq vm list        # etc.

# Dashboard screenshots — open browser to http://localhost:8888
freq serve &        # start dashboard
# Take browser screenshots of login page and fleet view
```
