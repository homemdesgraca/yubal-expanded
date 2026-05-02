# Yubal - Main Features Architecture

This document describes how yubal implements its core features. Yubal is a self-hosted YouTube Music downloader that takes a YouTube Music URL and produces a clean, tagged, organized music library.

---

## Table of Contents

- [0. Supported Sources](#0-supported-sources)
- [1. URL Parsing & Content Classification](#1-url-parsing--content-classification)
- [2. Metadata Extraction (YouTube Music API)](#2-metadata-extraction-youtube-music-api)
- [2b. MusicBrainz Enrichment](#2b-musicbrainz-enrichment)
- [3. Album Discovery & Track Matching](#3-album-discovery--track-matching)
- [4. Audio Download (yt-dlp)](#4-audio-download-yt-dlp)
- [5. Metadata Tagging & Cover Art Embedding](#5-metadata-tagging--cover-art-embedding)
- [6. Automatic Lyrics Fetching](#6-automatic-lyrics-fetching)
## 0. Supported Sources

Yubal supports two music sources:

| Source | Protocol | Metadata Source | Notes |
|--------|----------|-----------------|-------|
| **YouTube Music** | `ytmusicapi` | YouTube Music API | Full metadata, album classification, UGC support |
| **SoundCloud** | `yt-dlp --dump-json` | yt-dlp JSON parsing | No public API; uses yt-dlp for metadata extraction |

**YouTube Music:** Full feature set including album classification, track-to-album matching, and UGC downloads.

**SoundCloud:** Tracks and sets (playlists). No album classification (all content is `TRACK` or `PLAYLIST`). MusicBrainz enrichment available for canonical metadata.

---

## 2b. MusicBrainz Enrichment

**Feature:** Enriches baseline metadata from SoundCloud (yt-dlp) with canonical data from MusicBrainz.

**How it works:**

- `MusicBrainzClient` (`packages/yubal/src/yubal/client.py`) uses the `musicbrainzngs` library with `set_useragent("yubal", "0.8.0")` and `set_rate_limit(1.0)`.
- **Search:** `search_recordings(artist=..., recording=...)` finds the best matching recording.
- **Matching:** Uses the same `rapidfuzz` fuzzy matching logic as YouTube Music matching (70% threshold for title and artist).
- **Duration validation:** Rejects matches with >15% duration difference from the baseline.
- **Title normalization:** `normalize_title()` strips video suffixes (e.g., "(Official Video)") and feature credits (e.g., "ft Artist", "feat. Artist", "featuring Artist Name").
- **Enrichment:** If a confident MB match is found, replaces the SoundCloud baseline with MB data: year, release title (as album name), MBIDs.
- **Fallback:** If no MB match, uses the yt-dlp baseline metadata unchanged.
- **Protocol:** Implements `MusicBrainzProtocol` for dependency injection.
- **Configuration:** `MusicBrainzConfig` controls `enabled`, `search_limit` (default: 5), and `match_threshold` (default: 70%).

**Key files:**

| File | Role |
|------|------|
| `packages/yubal/src/yubal/client.py` | MusicBrainz client |
| `packages/yubal/src/yubal/config.py` | MusicBrainzConfig dataclass |
| `packages/yubal/src/yubal/lib/matching.py` | Fuzzy title/artist matching |
| `packages/yubal/src/yubal/services/extractor.py` | Enrichment pipeline |

---

- [7. ReplayGain Loudness Normalization](#7-replaygain-loudness-normalization)
- [8. M3U Playlist & Cover Art Generation](#8-m3u-playlist--cover-art-generation)
- [9. Smart Deduplication](#9-smart-deduplication)
- [10. Organized File Layout](#10-organized-file-layout)
- [11. Job Queue & Sequential Execution](#11-job-queue--sequential-execution)
- [12. Real-Time Progress via SSE](#12-real-time-progress-via-sse)
- [13. Scheduled Sync (Cron Scheduler)](#13-scheduled-sync-cron-scheduler)
- [14. Subscriptions Management](#14-subscriptions-management)
- [15. Browser Extension](#15-browser-extension)
- [16. CLI Interface](#16-cli-interface)
- [17. Cache Layer](#17-cache-layer)
- [18. Cookie-Based Authentication](#18-cookie-based-authentication)
- [19. Cancellation & Timeout Handling](#19-cancellation--timeout-handling)

---

## 1. URL Parsing & Content Classification

**Feature:** Accepts any YouTube Music URL (single track, album, or playlist) and automatically determines what kind of content it is.

**How it works:**

- **URL type detection** is handled by `yubal/utils/url.py`, which uses regex to extract `video_id` from watch URLs and `playlist_id` from playlist URLs.
- **Content classification** is done in `MetadataExtractorService._classify_playlist_as_album_or_playlist()` (`packages/yubal/src/yubal/services/extractor.py`). It applies a strict 4-check strategy:
  1. Playlist must have tracks
  2. All tracks must reference the same album ID
  3. The album must be fetchable from the YouTube Music API
  3. The playlist must contain ALL tracks from that album
- If all checks pass, the content is classified as `ContentKind.ALBUM`; otherwise, it's `ContentKind.PLAYLIST`. Single tracks are classified as `ContentKind.TRACK`.
- The `PlaylistInfoService` (`packages/api/src/yubal_api/services/playlist_info_service.py`) implements the same classification logic for the API's `/api/info` endpoint.

**Key files:**

| File | Role |
|------|------|
| `packages/yubal/src/yubal/utils/url.py` | URL parsing (video ID / playlist ID extraction) |
| `packages/yubal/src/yubal/services/extractor.py` | Classification logic |
| `packages/api/src/yubal_api/services/playlist_info_service.py` | API-side classification |

---

## 2. Metadata Extraction (YouTube Music API)

**Feature:** Fetches complete track metadata from YouTube Music, including title, artists, album info, track numbers, year, duration, and cover art URLs.

**How it works:**

- The `YTMusicClient` (`packages/yubal/src/yubal/client.py`) wraps the `ytmusicapi` library with consistent error handling and response parsing.
- It implements `YTMusicProtocol`, enabling dependency injection for testing.
- **Album caching:** The client maintains an LRU cache (max 128 albums) using `OrderedDict` to avoid redundant API calls for the same album.
- **Error classification:** The client parses ytmusicapi errors into specific domain errors: `AuthenticationRequiredError`, `PlaylistNotFoundError`, `UnsupportedPlaylistError`, `UpstreamAPIError`. It detects sign-in page responses by checking for patterns like "Sign in to listen".
- **Playlist fetching:** `get_playlist()` fetches all tracks (with `limit=None`), categorizes them as available or unavailable, and returns a parsed `Playlist` model.
- **Track fetching:** `get_track()` uses `get_watch_playlist()` to fetch a single track by video ID.

**SoundCloud alternative:** For SoundCloud URLs, `SoundCloudClient` uses `yt-dlp --dump-json --no-download <url>` to extract metadata. It handles both single tracks and sets (playlists), with NDJSON parsing for set entries. Implements `SoundCloudProtocol` for dependency injection.

**Key files:**

| File | Role |
|------|------|
| `packages/yubal/src/yubal/client.py` | YouTube Music + SoundCloud clients |
| `packages/yubal/src/yubal/models/media.py` | Domain models (Album, Playlist, Track, SoundCloudTrack, SoundCloudSet, etc.) |
| `packages/yubal/src/yubal/exceptions.py` | Domain-specific exceptions |

---

## 3. Album Discovery & Track Matching

**Feature:** When a playlist track lacks album information, yubal searches YouTube Music to find the canonical album and enriches the track with complete metadata.

**How it works:**

- **Search:** `MetadataExtractorService._search_for_album()` queries YouTube Music with `"artist + title"` and uses the `matching` module to find the best album match.
- **Title matching** (`packages/yubal/src/yubal/lib/matching.py`):
  - Strips common video suffixes (e.g., "(Official Video)", "(Official Audio)") and feature credits (e.g., "ft Artist", "feat. Artist", "featuring Artist Name")
  - Computes both full-title similarity and base-title similarity (stripping all parenthetical content)
  - Uses `rapidfuzz.fuzz.ratio` for string similarity scoring (threshold: 70%)
- **Artist matching:** Computes the best pairwise similarity between target and candidate artist sets (threshold: 70%).
- **Four-tier track-to-album matching** (`_match_playlist_track_to_album()`):
  1. Video ID match (most reliable)
  2. Exact title match (case-insensitive)
  3. Duration match (if unique within the album)
  4. Fuzzy title match using `rapidfuzz.process.extractOne` (threshold: 50-80%)

**Key files:**

| File | Role |
|------|------|
| `packages/yubal/src/yubal/lib/matching.py` | Fuzzy title and artist matching |
| `packages/yubal/src/yubal/services/extractor.py` | Album search orchestration |

---

## 4. Audio Download (yt-dlp)

**Feature:** Downloads audio from YouTube Music or SoundCloud using yt-dlp with support for multiple codecs (opus, mp3, m4a), automatic retry on transient errors, and graceful cancellation.

**How it works:**

- `YTDLPDownloader` (`packages/yubal/src/yubal/services/download_service.py`) wraps yt-dlp with consistent configuration:
  - **Video ID selection:** Prefers ATV video ID, falls back to OMV, then to `source_video_id` (which may be a SoundCloud permalink URL)
  - **URL handling:** If `source_video_id` is already a full URL (e.g., SoundCloud permalink), passes it directly to yt-dlp instead of wrapping in a YouTube Music URL
  - **Format selection:** Prefers best audio in the target codec, falls back to best available
  - **FFmpeg post-processing:** Converts to target codec with configurable quality
  - **Exponential backoff:** Retries transient errors (403, 429, 5xx) up to 3 times with delays of 1s, 2s, 4s (capped at 30s)
  - **Error classification:** Distinguishes non-retryable errors (video unavailable, authentication required) from retryable ones
  - **Cookie handling:** Copies cookies to a temp file to prevent yt-dlp from stripping entries needed by ytmusicapi
  - **Path capture:** Uses a postprocessor hook to capture the actual output path after FFmpeg completes
- **Video ID selection:** Prefers ATV (Audio Track Video) over OMV (Official Music Video) for best audio quality
- Implements `DownloaderProtocol` for dependency injection

**Key files:**

| File | Role |
|------|------|
| `packages/yubal/src/yubal/services/download_service.py` | Download orchestration |
| `packages/yubal/src/yubal/config.py` | Download configuration |

---

## 5. Metadata Tagging & Cover Art Embedding

**Feature:** Tags downloaded audio files with complete metadata (title, artist, album, track number, year, album artists) and embeds cover art.

**How it works:**

- `AudioFileTaggingService` (`packages/yubal/src/yubal/services/tagging_service.py`) uses the `mediafile` library for format-agnostic tagging:
  - **ID3 tags** for MP3 files
  - **Vorbis comments** for FLAC
  - **MP4 atoms** for M4A files
- **Multi-artist support:** Writes both singular `artist` (delimiter-joined for display/Jellyfin) and multi-value `artists` (preferred by Navidrome)
- **Cover art embedding:** Downloads cover art from YouTube using `fetch_cover()`, then embeds it using `mediafile.Image` which auto-detects format (JPEG vs PNG) from magic bytes
- Tagging is non-fatal: failures are logged but don't stop the download pipeline

**Key files:**

| File | Role |
|------|------|
| `packages/yubal/src/yubal/services/tagging_service.py` | Tag writing logic |
| `packages/yubal/src/yubal/utils/cover.py` | Cover art fetching with thread-safe cache |

---

## 6. Automatic Lyrics Fetching

**Feature:** Automatically fetches synced lyrics from lrclib.net and saves them as `.lrc` files alongside audio files.

**How it works:**

- `LyricsService` (`packages/yubal/src/yubal/services/lyrics.py`) makes a GET request to `https://lrclib.net/api/get` with track title, artist, and duration.
- Prefers synced lyrics (with timestamps) over plain lyrics.
- Saves as `<trackname>.lrc` alongside the audio file.
- Non-fatal: failures are logged at DEBUG level and don't affect download status.
- Skips if `.lrc` file already exists (idempotent).
- Implements `LyricsServiceProtocol` for dependency injection.

**Key files:**

| File | Role |
|------|------|
| `packages/yubal/src/yubal/services/lyrics.py` | Lyrics fetching |

---

## 7. ReplayGain Loudness Normalization

**Feature:** Applies ReplayGain/R128 tags to downloaded tracks for consistent volume across the library.

**How it works:**

- `ReplayGainService` (`packages/yubal/src/yubal/services/replaygain.py`) uses the `rsgain` CLI tool:
  - For **complete album downloads**: calculates both album gain and track gain (`-a` flag)
  - For **playlists or partial downloads**: calculates track gain only
  - For **Opus files**: uses RFC 7845 compliant R128 tags (`-o r` flag)
- Checks for `rsgain` availability via `shutil.which()` before attempting
- Gracefully falls back to track-only mode if some files are missing in album mode
- Non-fatal: failures are logged as warnings
- Command: `rsgain custom -q -s i [-a] [-o r] <files...>`

**Key files:**

| File | Role |
|------|------|
| `packages/yubal/src/yubal/services/replaygain.py` | ReplayGain application |

---

## 8. M3U Playlist & Cover Art Generation

**Feature:** Generates M3U playlist files and sidecar cover images for downloaded playlists.

**How it works:**

- `PlaylistArtifactsService` (`packages/yubal/src/yubal/services/artifacts.py`) orchestrates:
  - **M3U generation** (`packages/yubal/src/yubal/lib/m3u.py`): Writes extended M3U format with `#EXTM3U` header, `#EXTINF` duration lines, and relative paths to track files. Placed in `_Playlists/` directory.
  - **Cover art saving**: Downloads playlist cover as a sidecar `.jpg` file alongside the M3U.
- **Skips M3U for albums** (they have inherent folder structure) and single tracks.
- **Includes both SUCCESS and SKIPPED tracks** in M3U (SKIPPED means the file already existed).
- Filename format: `{Playlist Name} [{playlist_id_suffix}].m3u` (last 8 chars of playlist ID prevent collisions).

**Key files:**

| File | Role |
|------|------|
| `packages/yubal/src/yubal/services/artifacts.py` | Artifact generation orchestration |
| `packages/yubal/src/yubal/lib/m3u.py` | M3U file content generation |
| `packages/yubal/src/yubal/utils/cover.py` | Playlist cover writing |

---

## 9. Smart Deduplication

**Feature:** Same track across multiple playlists is stored once and referenced everywhere.

**How it works:**

- **Download skip logic** (`DownloadService.download_track()`): Before downloading, checks if the expected output file already exists on disk. If it does, the track is marked as `SKIPPED` with `SkipReason.FILE_EXISTS` and the download is skipped.
- **Lyrics for existing files**: Even skipped files still get lyrics fetched if they don't have `.lrc` files yet.
- **Extraction cache** (`packages/yubal/src/yubal/services/cache.py`): Persisted SQLite cache of previously extracted track metadata. When syncing a subscription, already-processed tracks use cached metadata instead of hitting the YouTube Music API again. Only confidently matched tracks (`MatchResult.MATCHED`) are cached.
- **Album API cache**: `YTMusicClient` maintains an in-memory LRU cache (128 albums) to avoid redundant API calls.
- **Cover art cache**: Thread-safe `CoverCache` class caches fetched cover art bytes to avoid redundant network requests.

**Key files:**

| File | Role |
|------|------|
| `packages/yubal/src/yubal/services/download_service.py` | File-existence check before download |
| `packages/yubal/src/yubal/services/cache.py` | Persistent extraction cache (SQLite) |
| `packages/yubal/src/yubal/client.py` | In-memory album cache |
| `packages/yubal/src/yubal/utils/cover.py` | Thread-safe cover art cache |

---

## 10. Organized File Layout

**Feature:** Downloads are organized into a clean directory structure that media servers understand.

**How it works:**

- **Matched tracks** (album tracks): `base/Artist/YEAR - Album/NN - Title.codec`
  - Example: `Pink Floyd/1973 - The Dark Side of the Moon/02 - Breathe.opus`
- **Unmatched tracks** (no confident album match): `base/_Unmatched/Artist - Title [videoId].codec`
  - The video ID ensures filename uniqueness
- **Unofficial/UGC tracks** (user-generated content): `base/_Unofficial/Artist - Title [videoId].codec`
- **Playlist M3U files**: `base/_Playlists/Playlist Name [id].m3u` + `base/_Playlists/Playlist Name [id].jpg`
- **Filename sanitization** (`packages/yubal/src/yubal/utils/filename.py`): Uses `pathvalidate` to remove invalid filename characters, with optional `unidecode` transliteration for unicode-to-ASCII conversion.

**Key files:**

| File | Role |
|------|------|
| `packages/yubal/src/yubal/utils/filename.py` | Path construction and sanitization |
| `packages/yubal/src/yubal/services/download_service.py` | Path resolution per match result |

---

## 11. Job Queue & Sequential Execution

**Feature:** Downloads are processed sequentially in FIFO order with a bounded queue.

**How it works:**

- `JobExecutor` (`packages/api/src/yubal_api/services/job_executor.py`) manages the job lifecycle:
  - Jobs are stored in a `JobExecutionStore` (SQLite-backed, defined in `packages/api/src/yubal_api/services/job_store.py`)
  - Only one job runs at a time; new jobs are queued and started when the previous one completes
  - Background tasks run in a thread pool via `asyncio.to_thread()` to avoid blocking the async event loop during I/O-heavy operations
  - `_start_next_pending()` is called after each job completes (in the `finally` block) to start the next queued job
  - **Timeout enforcement**: Each job has a configurable timeout (`YUBAL_JOB_TIMEOUT_SECONDS`, default 1800s) via `asyncio.timeout()`
  - **Partial file cleanup**: On cancellation, `.part` files are cleaned up via `cleanup_part_files()`

**Key files:**

| File | Role |
|------|------|
| `packages/api/src/yubal_api/services/job_executor.py` | Job orchestration |
| `packages/api/src/yubal_api/services/job_store.py` | Job persistence (SQLite) |
| `packages/api/src/yubal_api/domain/job.py` | Job domain model |

---

## 12. Real-Time Progress via SSE

**Feature:** The web UI receives real-time progress updates for all jobs via Server-Sent Events.

**How it works:**

- **Progress pipeline**: `PlaylistDownloadService` yields `PlaylistProgress` with phase, current/total counts. The `SyncService` (`packages/api/src/yubal_api/services/sync_service.py`) translates this to API-compatible progress callbacks with percentage calculations.
- **Phase ranges**: Extraction: 0-10%, Downloading: 10-85%, Composing: 85-90%, Normalizing: 90-100%.
- **Event bus**: `JobEventBus` (`packages/api/src/yubal_api/services/job_event_bus.py`) uses an `asyncio.Queue` to broadcast job state changes to all SSE subscribers.
- **SSE endpoint**: `GET /api/jobs/sse` streams events with an initial snapshot of all jobs, then real-time updates. Heartbeat comments are sent every 30s to keep connections alive.
- **Web UI**: The React frontend uses the EventSource API to subscribe to the SSE stream and updates the UI in real time.

**Key files:**

| File | Role |
|------|------|
| `packages/api/src/yubal_api/services/sync_service.py` | Progress translation |
| `packages/api/src/yubal_api/services/job_event_bus.py` | Event broadcasting |
| `packages/api/src/yubal_api/api/routes/jobs.py` | SSE endpoint |
| `web/src/api/logs.ts` | Frontend SSE consumer |

---

## 13. Scheduled Sync (Cron Scheduler)

**Feature:** Automatically syncs subscribed playlists at configurable intervals using cron expressions.

**How it works:**

- `Scheduler` (`packages/api/src/yubal_api/services/scheduler.py`) runs a background async task:
  - Uses `croniter` to calculate the next run time from the configured cron expression (default: `0 0 * * *` = midnight daily)
  - Runs in the configured timezone (`YUBAL_TZ`, default UTC)
  - Waits until the next run time, then triggers sync for all enabled subscriptions
  - Uses `asyncio.wait_for()` with the calculated timeout to avoid blocking
- Each subscription gets its own job created via `JobExecutor.create_and_start_job()`
- Subscription `last_synced_at` is updated when a job is created
- The scheduler can be enabled/disabled via `YUBAL_SCHEDULER_ENABLED`

**Key files:**

| File | Role |
|------|------|
| `packages/api/src/yubal_api/services/scheduler.py` | Cron-based scheduler |
| `packages/api/src/yubal_api/settings.py` | Scheduler settings |

---

## 14. Subscriptions Management

**Feature:** Users can subscribe to playlists/albums and have them automatically synced.

**How it works:**

- `SubscriptionService` (`packages/api/src/yubal_api/services/subscription_service.py`) handles CRUD:
  - **Create**: Validates the URL by fetching metadata, checks for duplicate URLs, creates a `Subscription` record
  - **Update**: Updates name/thumbnail (updated automatically when a sync job completes)
  - **Delete**: Removes the subscription record
  - **List**: Filters by enabled status and type
- Persisted in SQLite via `SubscriptionRepository` (`packages/api/src/yubal_api/db/subscription_repository.py`)
- SQLAlchemy ORM with Alembic migrations
- **Manual sync trigger**: Each subscription has a "sync now" button that creates an immediate job via `Scheduler.sync_subscription()`

**Key files:**

| File | Role |
|------|------|
| `packages/api/src/yubal_api/services/subscription_service.py` | Business logic |
| `packages/api/src/yubal_api/db/subscription.py` | SQLAlchemy model |
| `packages/api/src/yubal_api/db/subscription_repository.py` | Data access |
| `packages/api/src/yubal_api/api/routes/subscriptions.py` | REST endpoints |

---

## 15. Browser Extension

**Feature:** Chrome/Firefox extension that integrates directly into YouTube and YouTube Music pages.

**How it works:**

- Built with **WXT** (Web Extension Toolkit) for cross-browser compatibility (MV3 for Chrome, MV2 for Firefox).
- **Background script** (`extension/entrypoints/background.ts`):
  - Detects YouTube Music pages by checking if the tab URL matches YouTube media patterns
  - Dynamically changes the extension icon: colored icon on YouTube Music pages, grayscale otherwise
  - Uses `OffscreenCanvas` to generate grayscale icons at runtime
- **Popup** (`extension/entrypoints/popup/`): Provides the UI for downloading and subscribing
- **API integration** (`extension/lib/api.ts`): Communicates with the yubal server via REST API:
  - `POST /api/jobs` - Create a download job
  - `POST /api/subscriptions` - Subscribe to a playlist
  - `GET /api/info?url=` - Get content info for a URL
  - `GET /api/health` - Check server connectivity
- **Connection management**: Stores the server URL in extension storage, shows connection status in the popup

**Key files:**

| File | Role |
|------|------|
| `extension/entrypoints/background.ts` | Background service worker |
| `extension/entrypoints/popup/` | Popup UI |
| `extension/lib/api.ts` | API client |
| `extension/lib/storage.ts` | Extension storage |
| `extension/lib/youtube.ts` | YouTube URL detection |

---

## 16. CLI Interface

**Feature:** Download and inspect metadata from the terminal without the web UI.

**How it works:**

- Built with `argparse` in `packages/yubal/src/yubal/cli/`
- **Commands**:
  - `download` - Download tracks from a URL
  - `meta` - Inspect metadata for a URL without downloading
  - `tags` - Inspect tags on local audio files
  - `version` - Show version info
- Uses the same core services (`MetadataExtractorService`, `DownloadService`, `PlaylistDownloadService`) as the web API
- Supports the same configuration options (codec, quality, cookies, etc.)
- Progress is displayed as a CLI progress bar

**Key files:**

| File | Role |
|------|------|
| `packages/yubal/src/yubal/cli/main.py` | CLI entry point |
| `packages/yubal/src/yubal/cli/commands/download.py` | Download command |
| `packages/yubal/src/yubal/cli/commands/meta.py` | Metadata inspection |
| `packages/yubal/src/yubal/cli/formatting.py` | Output formatting |

---

## 17. Cache Layer

**Feature:** Persistent caching of extracted metadata to avoid redundant API calls.

**How it works:**

- `ExtractionCache` (`packages/yubal/src/yubal/services/cache.py`):
  - SQLite-backed persistent cache stored in the config directory (`extraction_cache.db`)
  - Keys by `source_video_id`
  - Only caches confidently matched tracks (`MatchResult.MATCHED`)
  - Unmatched/unofficial tracks are excluded so they can be re-attempted on subsequent syncs
  - Context manager pattern: `with cache: ...` for proper lifecycle management
  - Errors are swallowed to prevent cache failures from crashing syncs
- **Usage in pipeline**: The `PlaylistDownloadService` opens the cache before extraction, adds tracks as they're extracted, and closes it after. Cached tracks are returned immediately without API calls.

**Key files:**

| File | Role |
|------|------|
| `packages/yubal/src/yubal/services/cache.py` | Persistent extraction cache |

---

## 18. Cookie-Based Authentication

**Feature:** Supports YouTube cookies for age-restricted content, private playlists, and premium quality.

**How it works:**

- Cookies are stored at `config/ytdlp/cookies.txt` (or uploaded via the web UI)
- **For yt-dlp**: Copied to a temp file before download to prevent yt-dlp from stripping cookie entries. The temp file is deleted after download.
- **For ytmusicapi**: Cookies are converted to an `Authorization` header string via `cookies_to_ytmusic_auth()` which extracts the `SAPISID` cookie and computes the `SAPISID_HASH` auth string (same method YouTube uses internally).
- The `YTMusicClient` and `YTDLPDownloader` both accept optional `cookies_path` parameters.

**Key files:**

| File | Role |
|------|------|
| `packages/yubal/src/yubal/utils/cookies.py` | Cookie parsing and auth header generation |
| `packages/yubal/src/yubal/client.py` | Cookie-aware YTMusic client |
| `packages/yubal/src/yubal/services/download_service.py` | Cookie-aware yt-dlp downloader |

---

## 19. Cancellation & Timeout Handling

**Feature:** Downloads can be cancelled mid-operation and jobs have configurable timeouts.

**How it works:**

- **CancelToken** (`packages/yubal/src/yubal/models/cancel.py`): A simple flag (`is_cancelled`) checked at key points in the pipeline:
  - Before each phase starts in `PlaylistDownloadService`
  - During download via hooks in `YTDLPDownloader` (raises `DownloadCancelled` which is caught and re-raised as `CancellationError`)
  - In the progress callback in `JobExecutor._run_job()`
- **Job-level cancellation**: `JobExecutor.cancel_job()` sets the `CancelToken`, and `JobStore.cancel()` updates the job status to CANCELLED.
- **Timeout**: `asyncio.timeout(self._job_timeout)` wraps the entire sync operation. On timeout, the job is marked as FAILED and the cancel token is set.
- **Cleanup**: On cancellation, `cleanup_part_files()` removes any `.part` files left by yt-dlp.

**Key files:**

| File | Role |
|------|------|
| `packages/yubal/src/yubal/models/cancel.py` | CancelToken |
| `packages/api/src/yubal_api/services/job_executor.py` | Cancellation orchestration |
| `packages/yubal/src/yubal/utils/cleanup.py` | Partial file cleanup |

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser Extension                         │
│   (Chrome/Firefox - WXT)                                        │
│   Detects YT Music pages, talks to API                          │
└──────────────────────┬──────────────────────────────────────────┘
                       │ REST API (FastAPI)
┌──────────────────────▼──────────────────────────────────────────┐
│                        API Package                               │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │  Routes     │  │  JobExecutor │  │    Scheduler           │ │
│  │  (FastAPI)  │  │  (FIFO queue)│  │    (croniter)          │ │
│  └──────┬──────┘  └──────┬───────┘  └──────────┬─────────────┘ │
│         │                │                      │               │
│  ┌──────▼──────────────┐ │              ┌───────▼──────────┐   │
│  │   SyncService       │ │              │ SubscriptionSvc  │   │
│  │  (yubal adapter)    │ │              │ (CRUD + metadata)│   │
│  └──────┬──────────────┘ │              └──────────────────┘   │
│         │                │                                      │
│  ┌──────▼──────────────┐ │                                      │
│  │  JobStore (SQLite)  │ │                                      │
│  │  JobEventBus (SSE)  │ │                                      │
│  └─────────────────────┘ │                                      │
└──────────────┬───────────┘                                      │
               │                                                   │
┌──────────────▼─────────────────────────────────────────────────┐
│                       yubal Core Package                         │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │         PlaylistDownloadService (4-phase pipeline)       │   │
│  │  1. Extract → 2. Download → 3. Compose → 4. Normalize   │   │
│  └────┬───────────┬───────────┬──────────┬─────────┬───────┘   │
│       │           │           │          │         │           │
│  ┌────▼───┐  ┌────▼────┐ ┌───▼───┐ ┌────▼──┐ ┌────▼─────┐    │
│  │Extractor│  │Downloader│ │Artifacts│ │Replay│ │ LyricsSvc │   │
│  │(YTMusic │  │(yt-dlp) │ │(M3U+cover)│ │Gain│ │(lrclib)  │   │
│  │+SoundC │  │         │ │       │ │     │ │       │   │
│  │+MBEnrich│  │         │ │       │ │     │ │       │   │
│  └─────────┘  └─────────┘ └─────────┘ └──────┘ └──────────┘    │
│                                                                  │
│  ┌──────────────┐ ┌────────────┐ ┌──────────┐ ┌──────────────┐ │
│  │ Matching     │ │ Cache      │ │ Cover    │ │ Filename     │ │
│  │(rapidfuzz)   │ │(SQLite)    │ │Cache     │ │(pathvalidate)│ │
│  └──────────────┘ └────────────┘ └──────────┘ └──────────────┘ │
│                                                                  │
│  ┌──────────────┐ ┌──────────────┐                               │
│  │ YTMusicCli   │ │ SoundCloudCl │                               │
│  │ +MBClient    │ │ +MBClient    │                               │
│  └──────────────┘ └──────────────┘                               │
└──────────────────────────────────────────────────────────────────┘
```
