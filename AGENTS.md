This is **yubal-expanded**, an ongoing fork of [Yubal](https://github.com/guillevc/yubal) by "guillevc", adding SoundCloud support and other features that deviate from the original project's scope.

Use ./docs/summary.md for a clear summary of how the project works.

Key files:
- AGENTS.md - This file, project context for AI agents
- pyproject.toml - Workspace config (members: packages/*)
- packages/yubal/src/yubal/ - Core yubal library
- packages/api/src/yubal_api/ - API server
- web/src/ - Frontend (Vite)

## SoundCloud fork status

Full SoundCloud support is complete (all phases done, 537 tests passing). Key additions over the original Yubal project:

- **SoundCloud extraction** via yt-dlp (no public API available)
- **MusicBrainz enrichment** for SoundCloud tracks (year, track number, album, MBIDs)
- **Cover Art Archive** integration for fallback cover art on unmatched tracks
- **SoundCloud subscriptions** via the API layer (oembed metadata, sub-second preview)
- **Browser extension** with SoundCloud icon detection, orange SC icons, URL routing
- **Filename fix**: UNMATCHED/UNOFFICIAL tracks use short numeric SoundCloud IDs (not full permalinks)

Known notes (not actionable issues):
- Genre tagging intentionally skipped
- Without MB enrichment, SoundCloud tracks land in `_Unmatched/` flat folder
- SAPISID cookie missing affects YouTube Music API (not SoundCloud)
