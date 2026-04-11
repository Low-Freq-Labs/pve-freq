# Screenshot Capture Guide

Terminal settings for consistent screenshots:

- **Background:** Dark (#0a0d12 or similar)
- **Font:** Monospace, 14px
- **Width:** 120 columns minimum
- **Tool:** `gnome-screenshot`, `scrot`, macOS `Cmd+Shift+4`, or any screen capture

## Required Screenshots

### 1. Dashboard Home (`dashboard-home.png`)

```bash
freq serve &
# Open http://localhost:8888 in browser
# Screenshot the home view with fleet status cards visible
```

### 2. TUI Main Menu (`tui-menu.png`)

```bash
freq menu
# Screenshot showing the main menu with categories and risk tags
```

### 3. CLI Fleet Status (`cli-status.png`)

```bash
freq fleet status
# Screenshot showing the fleet table with colored badges
```

### 4. CLI Doctor (`cli-doctor.png`)

```bash
freq doctor
# Screenshot showing the bordered diagnostic output with check marks
```

### 5. Demo Mode (`cli-demo.png`)

```bash
freq demo
# Screenshot the personality showcase section
```

### 6. CLI Splash (`cli-splash.png`)

```bash
freq version
# Screenshot the ASCII logo + tagline
```

## File Naming

Use the exact filenames above. The README references them directly.
Place all PNG files in this directory (`docs/screenshots/`).
