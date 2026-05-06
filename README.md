# yubal-expanded

A fork of [Yubal](https://github.com/guillevc/yubal) by guillevc, adding SoundCloud support and other features.

## Features

- **YouTube Music** - albums, playlists, tracks
- **SoundCloud** - tracks and sets
- Scheduled sync & smart deduplication
- Browser extension included
- Media server ready (Navidrome, Jellyfin etc...)

### Planned features

- [ ] More config options directly from the WebUI
- [ ] Subscribing to ListenBrainz auto-generated playlists

## Docker Quick Start

```yaml
services:
  yubal:
    image: ghcr.io/homemdesgraca/yubal-expanded:dev
    container_name: yubal-expanded
    network_mode: host
    restart: unless-stopped
    user: "1000:1000"
    environment:
      - YUBAL_PORT=8000
    volumes:
      - <PATH_TO_CONFIGFOLDER>:/app/config
      - <PATH_TO_LIBRARY>:/app/data
```

```bash
docker compose up -d
```

## Browser Extension

Download tracks and subscribe to playlists from YouTube Music and SoundCloud directly from the browser:

- [Extension for Chrome/Chromium and Firefox](https://github.com/homemdesgraca/yubal-expanded/releases/latest)

## Configuration

Same as the original Yubal project. See the [original README](https://github.com/guillevc/yubal) for the full config reference.

## Original Yubal

This project is a fork of [Yubal](https://github.com/guillevc/yubal) by [guillevc](https://github.com/guillevc).

Support them with the links below:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/guillevc) [![Sponsor](https://img.shields.io/badge/sponsor-GitHub-ea4aaa?logo=github)](https://github.com/sponsors/guillevc)
