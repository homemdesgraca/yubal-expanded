"""YouTube Music API client wrapper."""

import json
import logging
import re
import shutil
import subprocess
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Protocol, cast

from ytmusicapi import YTMusic
from ytmusicapi.exceptions import YTMusicError, YTMusicServerError, YTMusicUserError

from yubal.config import APIConfig, MusicBrainzConfig
from yubal.exceptions import (
    AuthenticationRequiredError,
    PlaylistNotFoundError,
    SoundCloudParseError,
    SoundCloudUnavailableError,
    TrackNotFoundError,
    UnsupportedPlaylistError,
    UpstreamAPIError,
    YubalError,
)
from yubal.models.enums import SkipReason
from yubal.models.media import (
    Album,
    Playlist,
    PlaylistTrack,
    SearchResult,
    SoundCloudSet,
    SoundCloudTrack,
)
from yubal.utils.cookies import cookies_to_ytmusic_auth

logger = logging.getLogger(__name__)

# Maximum number of albums to cache per client instance
_ALBUM_CACHE_SIZE = 128


class YTMusicProtocol(Protocol):
    """Protocol for YouTube Music API clients.

    This protocol enables dependency injection and testing.
    Implement this protocol to create mock clients for testing.
    """

    def get_playlist(self, playlist_id: str) -> Playlist:
        """Fetch a playlist by ID."""
        ...

    def get_album(self, album_id: str) -> Album:
        """Fetch an album by ID."""
        ...

    def search_songs(self, query: str) -> list[SearchResult]:
        """Search for songs."""
        ...

    def get_track(self, video_id: str) -> PlaylistTrack:
        """Fetch a single track by video ID."""
        ...


class SoundCloudProtocol(Protocol):
    """Protocol for SoundCloud metadata clients.

    This protocol enables dependency injection and testing.
    Implement this protocol to create mock clients for testing.
    """

    def get_track(self, url: str) -> SoundCloudTrack:
        """Fetch metadata for a single SoundCloud track.

        Args:
            url: SoundCloud track URL.

        Returns:
            Parsed SoundCloudTrack model.

        Raises:
            SoundCloudParseError: If metadata cannot be parsed.
            SoundCloudUnavailableError: If the track is private or removed.
        """
        ...

    def get_set(self, url: str) -> SoundCloudSet:
        """Fetch metadata for a SoundCloud set (playlist).

        Args:
            url: SoundCloud set URL.

        Returns:
            Parsed SoundCloudSet model with all tracks.

        Raises:
            SoundCloudParseError: If metadata cannot be parsed.
            SoundCloudUnavailableError: If the set is private or removed.
        """
        ...

    def extract(self, url: str) -> SoundCloudTrack | SoundCloudSet:
        """Extract metadata from a SoundCloud URL (track or set).

        Auto-detects the URL type and returns the appropriate model.

        Args:
            url: SoundCloud track or set URL.

        Returns:
            Parsed SoundCloudTrack or SoundCloudSet model.

        Raises:
            SoundCloudParseError: If metadata cannot be parsed.
            SoundCloudUnavailableError: If the content is private or removed.
        """
        ...


class MusicBrainzProtocol(Protocol):
    """Protocol for MusicBrainz API clients.

    This protocol enables dependency injection and testing.
    Implement this protocol to create mock clients for testing.
    """

    def enrich_track(
        self,
        title: str,
        artists: list[str],
        duration_seconds: int,
    ) -> dict[str, Any] | None:
        """Search MusicBrainz for the best recording match.

        Args:
            title: Track title.
            artists: List of artist names.
            duration_seconds: Track duration for additional matching.

        Returns:
            Dict with MBID and metadata if a confident match found, None otherwise.
        """
        ...


class YTMusicClient:
    """Production YouTube Music API client.

    Wraps ytmusicapi with consistent error handling and response parsing.
    Implements YTMusicProtocol for type safety.
    """

    def __init__(
        self,
        ytmusic: YTMusic | None = None,
        config: APIConfig | None = None,
        cookies_path: Path | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            ytmusic: Optional YTMusic instance. Creates one if not provided.
            config: Optional API configuration. Uses defaults if not provided.
            cookies_path: Optional path to cookies.txt for authentication.
                         If provided and valid, enables authenticated requests.
        """
        if ytmusic:
            self._ytm = ytmusic
        else:
            self._ytm = self._create_ytmusic(cookies_path)
        self._config = config or APIConfig()
        # LRU cache for albums with size limit
        self._album_cache: OrderedDict[str, Album] = OrderedDict()

    def _create_ytmusic(self, cookies_path: Path | None) -> YTMusic:
        """Create YTMusic instance with optional authentication.

        Args:
            cookies_path: Optional path to cookies.txt file.

        Returns:
            Configured YTMusic instance.
        """
        if cookies_path:
            auth = cookies_to_ytmusic_auth(cookies_path)
            if auth:
                logger.info("Using cookies for ytmusicapi requests")
                return YTMusic(auth=auth)
            logger.info("No valid cookies for ytmusicapi requests (missing SAPISID)")
            return YTMusic()

        logger.info("No cookies configured for ytmusicapi requests")
        return YTMusic()

    def get_playlist(self, playlist_id: str) -> Playlist:
        """Fetch a playlist by ID.

        Args:
            playlist_id: YouTube Music playlist ID.

        Returns:
            Parsed Playlist model.

        Raises:
            ValueError: If playlist_id is empty.
            PlaylistNotFoundError: If playlist doesn't exist or is inaccessible.
            AuthenticationRequiredError: If playlist requires authentication.
            UnsupportedPlaylistError: If playlist type is not supported.
            UpstreamAPIError: If API request fails.
        """
        if not playlist_id or not playlist_id.strip():
            raise ValueError("playlist_id cannot be empty")

        # Check for unsupported playlist prefixes before making API call
        self._check_playlist_type(playlist_id)

        logger.debug("Fetching playlist: %s", playlist_id)
        try:
            data = self._ytm.get_playlist(playlist_id, limit=None)
        except (YTMusicServerError, YTMusicUserError) as e:
            error_msg = str(e)
            logger.warning("YTMusic API error for playlist %s: %s", playlist_id, e)

            # Parse error to provide better error messages
            specific_error = self._parse_playlist_error(error_msg, playlist_id)
            if specific_error:
                raise specific_error from e

            raise UpstreamAPIError(f"Failed to fetch playlist: {e}") from e
        except YTMusicError as e:
            logger.warning("YTMusic error for playlist %s: %s", playlist_id, e)
            raise UpstreamAPIError(f"Failed to fetch playlist: {e}") from e
        except (KeyError, TypeError) as e:
            error_msg = str(e)
            logger.warning("Missing data in playlist response %s: %s", playlist_id, e)

            # Check if YouTube returned a "Sign in" page (auth failure)
            if isinstance(e, KeyError) and self._is_sign_in_response(error_msg):
                raise AuthenticationRequiredError(
                    "Authentication failed. YouTube returned a 'Sign in' page instead "
                    "of playlist data. Your cookies may be invalid, expired, or from "
                    "a non-authenticated session. Please re-export your cookies while "
                    "logged into YouTube Music."
                ) from e

            raise PlaylistNotFoundError(
                f"Playlist not found or malformed: {playlist_id}"
            ) from e

        if not data:
            raise PlaylistNotFoundError(f"Playlist not found: {playlist_id}")

        # Categorize tracks: available vs unavailable with reasons
        raw_tracks = data.get("tracks") or []
        valid_tracks: list[dict] = []
        unavailable_tracks: list[dict] = []

        for track in raw_tracks:
            if not track:
                continue

            video_id = track.get("videoId")
            is_available = track.get("isAvailable", True)

            # Extract metadata for display
            title = track.get("title")
            artists = [
                name for a in (track.get("artists") or []) if (name := a.get("name"))
            ]
            album_info = track.get("album")
            album_name = (
                album_info.get("name") if isinstance(album_info, dict) else None
            )

            if not video_id:
                unavailable_tracks.append(
                    {
                        "title": title,
                        "artists": artists,
                        "album": album_name,
                        "reason": SkipReason.NO_VIDEO_ID.value,
                    }
                )
            elif not is_available:
                unavailable_tracks.append(
                    {
                        "title": title,
                        "artists": artists,
                        "album": album_name,
                        "reason": SkipReason.REGION_UNAVAILABLE.value,
                    }
                )
            else:
                valid_tracks.append(self._normalize_playlist_track(track))

        data["tracks"] = valid_tracks
        data["unavailable_tracks"] = unavailable_tracks

        logger.debug(
            "Fetched playlist with %d valid tracks (%d unavailable)",
            len(valid_tracks),
            len(unavailable_tracks),
        )
        return Playlist.model_validate(data)

    def _normalize_playlist_track(self, track: dict[str, Any]) -> dict[str, Any]:
        """Normalize playlist track fields before model validation."""
        normalized = dict(track)

        # ytmusicapi may return null for artists on some tracks.
        if normalized.get("artists") is None:
            normalized["artists"] = []

        return normalized

    def get_album(self, album_id: str) -> Album:
        """Fetch an album by ID.

        Results are cached with LRU eviction (max 128 albums).

        Args:
            album_id: YouTube Music album ID.

        Returns:
            Parsed Album model.

        Raises:
            UpstreamAPIError: If API request fails.
        """
        if album_id in self._album_cache:
            logger.debug("Album cache hit: %s", album_id)
            # Move to end (most recently used)
            self._album_cache.move_to_end(album_id)
            return self._album_cache[album_id]

        logger.debug("Fetching album: %s", album_id)
        try:
            data = self._ytm.get_album(album_id)
        except (YTMusicServerError, YTMusicUserError) as e:
            logger.warning("YTMusic API error for album %s: %s", album_id, e)
            raise UpstreamAPIError(f"Failed to fetch album: {e}") from e
        except YTMusicError as e:
            logger.warning("YTMusic error for album %s: %s", album_id, e)
            raise UpstreamAPIError(f"Failed to fetch album: {e}") from e

        album = Album.model_validate(data)

        # Add to cache with LRU eviction
        self._album_cache[album_id] = album
        if len(self._album_cache) > _ALBUM_CACHE_SIZE:
            # Remove oldest (first) item
            self._album_cache.popitem(last=False)

        return album

    def search_songs(self, query: str) -> list[SearchResult]:
        """Search for songs.

        Args:
            query: Search query string.

        Returns:
            List of parsed SearchResult models.

        Raises:
            UpstreamAPIError: If API request fails.
        """
        logger.debug("Searching songs: %s", query)
        try:
            data = self._ytm.search(
                query,
                filter="songs",
                limit=self._config.search_limit,
                ignore_spelling=self._config.ignore_spelling,
            )
        except (YTMusicServerError, YTMusicUserError) as e:
            logger.warning("YTMusic API error for search '%s': %s", query, e)
            raise UpstreamAPIError(f"Search failed: {e}") from e
        except YTMusicError as e:
            logger.warning("YTMusic error for search '%s': %s", query, e)
            raise UpstreamAPIError(f"Search failed: {e}") from e

        return [SearchResult.model_validate(r) for r in data]

    def get_track(self, video_id: str) -> PlaylistTrack:
        """Fetch a single track by video ID using get_watch_playlist().

        Args:
            video_id: YouTube video ID.

        Returns:
            Parsed PlaylistTrack model.

        Raises:
            ValueError: If video_id is empty.
            TrackNotFoundError: If track doesn't exist or is inaccessible.
            UpstreamAPIError: If API request fails.
        """
        if not video_id or not video_id.strip():
            raise ValueError("video_id cannot be empty")

        logger.debug("Fetching track: %s", video_id)
        try:
            data = self._ytm.get_watch_playlist(video_id)
        except (YTMusicServerError, YTMusicUserError) as e:
            logger.warning("YTMusic API error for track %s: %s", video_id, e)
            raise UpstreamAPIError(f"Failed to fetch track: {e}") from e
        except YTMusicError as e:
            logger.warning("YTMusic error for track %s: %s", video_id, e)
            raise UpstreamAPIError(f"Failed to fetch track: {e}") from e

        tracks = cast(list[dict[str, Any]], data.get("tracks") or [])
        if not tracks:
            raise TrackNotFoundError(f"Track not found: {video_id}")

        track_data = self._normalize_watch_track(tracks[0])
        return PlaylistTrack.model_validate(track_data)

    def _normalize_watch_track(self, track: dict) -> dict:
        """Normalize get_watch_playlist track to PlaylistTrack format.

        The get_watch_playlist API returns tracks with different field names:
        - 'thumbnail' instead of 'thumbnails'
        - 'length' (string) instead of 'duration_seconds' (int)
        """
        result = dict(track)

        # Normalize thumbnail -> thumbnails
        if "thumbnail" in result and "thumbnails" not in result:
            result["thumbnails"] = result.pop("thumbnail")

        # Normalize length -> duration_seconds
        if "length" in result and "duration_seconds" not in result:
            result["duration_seconds"] = self._parse_duration(result.pop("length"))

        return result

    def _parse_duration(self, length: str) -> int:
        """Parse duration string like '3:00' or '1:23:45' to seconds.

        Returns 0 for unparseable formats (logs warning).
        """
        if not length:
            return 0

        try:
            parts = length.split(":")
            if len(parts) == 2:
                minutes, seconds = int(parts[0]), int(parts[1])
                return minutes * 60 + seconds
            elif len(parts) == 3:
                hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
                return hours * 3600 + minutes * 60 + seconds
            logger.warning("Unexpected duration format: %s", length)
            return 0
        except ValueError:
            logger.warning("Could not parse duration: %s", length)
            return 0

    def clear_album_cache(self) -> None:
        """Clear the album cache."""
        self._album_cache.clear()
        logger.debug("Album cache cleared")

    def get_album_cache_size(self) -> int:
        """Get the number of cached albums.

        Returns:
            Number of album IDs currently cached.
        """
        return len(self._album_cache)

    def _check_playlist_type(self, playlist_id: str) -> None:
        """Check if playlist type is supported before fetching.

        Args:
            playlist_id: Playlist ID to check.

        Raises:
            UnsupportedPlaylistError: If playlist type is not supported.
        """
        # Known unsupported playlist prefixes (confirmed to fail)
        # Note: Many RD* prefixes (like RDTMAK) actually work fine
        unsupported_prefixes = {
            "LRSRK": "Recap playlists",  # Seasonal/yearly recaps
            "SE": "Episodes",  # Podcast episodes
        }

        for prefix, playlist_type in unsupported_prefixes.items():
            if playlist_id.startswith(prefix):
                raise UnsupportedPlaylistError(
                    f"{playlist_type} are auto-generated by YouTube Music and use "
                    "a different API format that is not supported. "
                    "Try saving the playlist to your library first."
                )

    def _is_sign_in_response(self, error_msg: str) -> bool:
        """Check if error indicates YouTube returned a 'Sign in' page.

        When cookies are invalid/expired, YouTube returns a page asking the user
        to sign in instead of the expected playlist data. ytmusicapi then raises
        a KeyError because expected fields are missing.

        Args:
            error_msg: Error message from ytmusicapi KeyError.

        Returns:
            True if error indicates auth failure (sign-in page returned).
        """
        # These patterns indicate YouTube returned a sign-in page
        sign_in_indicators = [
            "'Sign in'",
            "Sign in to listen",
            "signInEndpoint",
            "singleColumnBrowseResultsRenderer",  # Used for sign-in pages
        ]
        return any(indicator in error_msg for indicator in sign_in_indicators)

    def _parse_playlist_error(
        self, error_msg: str, playlist_id: str
    ) -> YubalError | None:
        """Parse ytmusicapi error to determine specific error type.

        Args:
            error_msg: Error message from ytmusicapi.
            playlist_id: The playlist ID that was requested.

        Returns:
            Specific exception if error type can be determined, None otherwise.
        """
        # Check for the "contents" KeyError which indicates empty/inaccessible playlist
        if "Unable to find 'contents'" not in error_msg:
            return None

        # Check if user is logged in by looking for logged_in value in error
        is_logged_in = "'logged_in', 'value': '1'" in error_msg

        # Check for noindex flag which indicates private/special playlist
        is_noindex = "'noindex': True" in error_msg

        if is_noindex:
            if is_logged_in:
                # User is authenticated but still can't access - unsupported type
                return UnsupportedPlaylistError(
                    "This playlist type is not supported. YouTube Music "
                    "auto-generated playlists (Recap, Discover Mix, etc.) use a "
                    "different API format. Try saving the playlist to your "
                    "library first, then use the saved copy."
                )
            else:
                # User is not authenticated - might be a private playlist
                return AuthenticationRequiredError(
                    "This playlist may be private and requires authentication. "
                    "Please upload your YouTube Music cookies via the web UI to "
                    "access private playlists. Go to Settings and upload a "
                    "cookies.txt file exported from your browser while logged "
                    "into YouTube Music."
                )

        # Generic case - playlist might be deleted or invalid
        if not is_logged_in:
            return AuthenticationRequiredError(
                "Unable to access playlist. This may be a private playlist that "
                "requires authentication. Please upload your YouTube Music "
                "cookies to access private content."
            )

        return None


# ============================================================================
# SOUND CLOUD CLIENT
# ============================================================================


class SoundCloudClient:
    """SoundCloud metadata client using yt-dlp.

    Extracts track and set metadata from SoundCloud URLs by running
    ``yt-dlp --dump-json --no-download <url>`` and parsing the JSON output.
    Implements SoundCloudProtocol for dependency injection.

    Why yt-dlp: SoundCloud does not offer a public API for metadata.
    yt-dlp provides reliable extraction of track info, artwork URLs,
    and set contents without downloading the audio file.

    Edge cases handled:
    - Tracks without artist names -> skipped (has_valid_metadata=False)
    - Tracks without duration -> skipped (has_valid_metadata=False)
    - Private/restricted tracks -> SoundCloudUnavailableError
    - Missing artwork -> artwork_url is None (graceful degradation)
    """

    def __init__(self, yt_dlp_path: str | None = None) -> None:
        """Initialize the client.

        Args:
            yt_dlp_path: Optional path to yt-dlp binary. Uses PATH search if None.
        """
        self._yt_dlp_path = yt_dlp_path or "yt-dlp"

    def _run_dump_json(self, url: str) -> dict[str, Any]:
        """Run yt-dlp --dump-json --no-download for a SoundCloud URL.

        Args:
            url: SoundCloud track or set URL.

        Returns:
            Parsed JSON output as a dict.

        Raises:
            SoundCloudUnavailableError: If the track/set is private or removed.
            SoundCloudParseError: If yt-dlp output cannot be parsed.
        """
        logger.debug("Running yt-dlp --dump-json for: %s", url)

        cmd = [self._yt_dlp_path, "--dump-json", "--no-download", "--no-warnings", url]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except FileNotFoundError:
            raise SoundCloudParseError(
                "yt-dlp is not installed or not in PATH. "
                "Please install yt-dlp: pip install yt-dlp"
            )
        except subprocess.TimeoutExpired:
            raise SoundCloudParseError(
                f"yt-dlp timed out after 30s for: {url}"
            )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            # Check for common unavailability patterns
            if any(
                pattern in stderr
                for pattern in [
                    "This track is no longer available",
                    "This song is unavailable",
                    "Private or internal",
                    "This content is private",
                    "has been removed by the artist",
                    "This video is unavailable",
                    "Access denied",
                    "This track has been blocked",
                    "country_limit",
                    "geoblocked",
                    "REGION_RESTRICTED",
                ]
            ):
                raise SoundCloudUnavailableError(
                    f"SoundCloud track is unavailable: {stderr[:200]}"
                )
            raise SoundCloudParseError(
                f"yt-dlp failed (code {result.returncode}): {stderr[:200]}"
            )

        stdout = result.stdout.strip()
        return self._parse_json_output(stdout)

    def _parse_json_output(self, stdout: str) -> dict[str, Any]:
        """Parse JSON output from yt-dlp, handling both single-object and NDJSON.

        For single-track URLs, yt-dlp returns a single JSON object.
        For set URLs, yt-dlp returns NDJSON (newline-delimited JSON),
        where each line is a separate track entry.

        Args:
            stdout: Raw stdout from yt-dlp.

        Returns:
            For single-track: dict with track metadata.
            For sets: dict with ``_type": "video_list"`` and ``entries`` list.

        Raises:
            SoundCloudParseError: If output cannot be parsed.
        """
        lines = stdout.split("\n")
        # Filter out empty lines
        lines = [line.strip() for line in lines if line.strip()]

        if len(lines) == 1:
            # Single JSON object (track)
            try:
                return json.loads(lines[0])
            except json.JSONDecodeError as e:
                raise SoundCloudParseError(
                    f"yt-dlp output is not valid JSON: {e}"
                )

        # Multiple lines — NDJSON (set)
        entries: list[dict[str, Any]] = []
        for i, line in enumerate(lines):
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                logger.debug("Skipping non-JSON line #%d", i + 1)
                continue

        if not entries:
            raise SoundCloudParseError("No valid JSON entries in yt-dlp output")

        # Build a set-like structure from entries
        # Use the first entry for set-level metadata
        first = entries[0]
        return {
            "_type": "video_list",
            "id": first.get("playlist_id") or first.get("id") or "",
            "title": first.get("playlist_title") or first.get("track")
            or first.get("title", ""),
            "uploader": first.get("playlist_uploader") or first.get("uploader"),
            "track_count": first.get("n_entries") or len(entries),
            "entries": entries,
        }

    def get_track(self, url: str) -> SoundCloudTrack:
        """Fetch metadata for a single SoundCloud track.

        Runs ``yt-dlp --dump-json --no-download <url>`` and parses the
        JSON output into a SoundCloudTrack model.

        Args:
            url: SoundCloud track URL.

        Returns:
            Parsed SoundCloudTrack model.

        Raises:
            SoundCloudParseError: If metadata cannot be parsed.
            SoundCloudUnavailableError: If the track is private or removed.
        """
        data = self._run_dump_json(url)
        return self._parse_track(data)

    def get_set(self, url: str) -> SoundCloudSet:
        """Fetch metadata for a SoundCloud set (playlist).

        Runs ``yt-dlp --dump-json --no-download <url>`` and parses the
        JSON output. For sets, yt-dlp returns NDJSON (one JSON object per
        line), which is parsed into a ``video_list`` structure with all
        entries.

        Args:
            url: SoundCloud set URL.

        Returns:
            Parsed SoundCloudSet model with all tracks.

        Raises:
            SoundCloudParseError: If metadata cannot be parsed.
            SoundCloudUnavailableError: If the set is private or removed.
        """
        data = self._run_dump_json(url)

        # Check if this is a set (video_list type with entries)
        if data.get("_type") == "video_list":
            entries = data.get("entries") or []
            return self._parse_set(data, entries)

        # Single track URL that was somehow passed to get_set
        # Try parsing as a single track and wrapping it
        track = self._parse_track(data)
        return SoundCloudSet(
            id=track.id,
            title=track.title,
            artist=track.artist,
            tracks=[track],
            artwork_url=track.artwork_url,
            permalink_url=track.permalink_url,
        )

    def extract(self, url: str) -> SoundCloudTrack | SoundCloudSet:
        """Extract metadata from a SoundCloud URL (track or set).

        Auto-detects the URL type and returns the appropriate model.

        Args:
            url: SoundCloud track or set URL.

        Returns:
            Parsed SoundCloudTrack or SoundCloudSet model.

        Raises:
            SoundCloudParseError: If metadata cannot be parsed.
            SoundCloudUnavailableError: If the content is private or removed.
        """
        # Check for set URL pattern
        if "/sets/" in url:
            return self.get_set(url)
        return self.get_track(url)

    def _parse_track(self, data: dict[str, Any]) -> SoundCloudTrack:
        """Parse a yt-dlp JSON response into a SoundCloudTrack.

        Handles both single-track and set-entry responses.

        Args:
            data: yt-dlp JSON output dict.

        Returns:
            Parsed SoundCloudTrack model.

        Raises:
            SoundCloudParseError: If required fields are missing.
        """
        # Extract basic fields with sensible defaults
        track_id = data.get("id") or data.get("_id", "")
        title = data.get("title") or data.get("name", "")
        duration = data.get("duration") or data.get("duration_string")

        # Parse duration: can be int (seconds) or string like "3:24"
        duration_seconds = self._parse_duration(duration)

        # Extract artist name
        artist = ""
        uploader = data.get("uploader") or data.get("creator") or data.get("artist")
        if isinstance(uploader, str):
            artist = uploader
        elif isinstance(uploader, dict):
            artist = uploader.get("title") or uploader.get("name") or ""

        # Extract artwork URL
        artwork_url = None
        thumbnails = data.get("thumbnails") or data.get("thumbnail")
        if isinstance(thumbnails, list) and thumbnails:
            # Pick the largest thumbnail
            largest = max(thumbnails, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))
            artwork_url = largest.get("url")
        elif isinstance(thumbnails, str):
            artwork_url = thumbnails
        elif isinstance(thumbnails, dict):
            artwork_url = thumbnails.get("url")

        # Extract permalink URL
        permalink_url = (
            data.get("webpage_url")
            or data.get("url")
            or data.get("permalink_url")
            or data.get("external_url")
        )

        if not track_id:
            raise SoundCloudParseError("Missing track ID in SoundCloud response")
        if not title:
            raise SoundCloudParseError("Missing title in SoundCloud response")

        return SoundCloudTrack(
            id=str(track_id),
            title=title,
            artist=artist,
            duration_seconds=duration_seconds,
            artwork_url=artwork_url,
            permalink_url=permalink_url,
        )

    def _parse_track_with_position(
        self, data: dict[str, Any], position: int, total_tracks: int
    ) -> SoundCloudTrack:
        """Parse a yt-dlp JSON response into a SoundCloudTrack with set position.

        Args:
            data: yt-dlp JSON output dict.
            position: 1-based track position in the set.
            total_tracks: Total number of tracks in the set.

        Returns:
            Parsed SoundCloudTrack model with track_number and total_tracks set.

        Raises:
            SoundCloudParseError: If required fields are missing.
        """
        track = self._parse_track(data)
        track = SoundCloudTrack(
            id=track.id,
            title=track.title,
            artist=track.artist,
            duration_seconds=track.duration_seconds,
            artwork_url=track.artwork_url,
            permalink_url=track.permalink_url,
            track_number=position,
            total_tracks=total_tracks,
        )
        return track

    def _parse_set(
        self, data: dict[str, Any], entries: list[dict[str, Any]]
    ) -> SoundCloudSet:
        """Parse a SoundCloud set from yt-dlp JSON output.

        Args:
            data: Top-level yt-dlp JSON output dict (for set metadata).
            entries: List of track entry dicts from ``data["entries"]``.

        Returns:
            Parsed SoundCloudSet model.
        """
        # Set-level metadata
        set_id = data.get("id") or data.get("_id", "")
        set_title = data.get("title") or data.get("name", "")

        set_artist = ""
        uploader = data.get("uploader") or data.get("creator") or data.get("artist")
        if isinstance(uploader, str):
            set_artist = uploader
        elif isinstance(uploader, dict):
            set_artist = uploader.get("title") or uploader.get("name") or ""

        # Set-level artwork
        set_artwork = None
        thumbnails = data.get("thumbnails") or data.get("thumbnail")
        if isinstance(thumbnails, list) and thumbnails:
            largest = max(thumbnails, key=lambda t: (t.get("width") or 0) * (t.get("height") or 0))
            set_artwork = largest.get("url")
        elif isinstance(thumbnails, str):
            set_artwork = thumbnails

        # Parse individual tracks
        tracks: list[SoundCloudTrack] = []
        total = data.get("track_count") or len(entries)
        for i, entry in enumerate(entries):
            try:
                # Parse track with set position info
                track = self._parse_track_with_position(entry, i + 1, total)
            except SoundCloudParseError:
                logger.debug("Skipping malformed entry #%d in set %s", i + 1, set_id)
                continue

            tracks.append(track)

        if not tracks:
            raise SoundCloudParseError(
                f"No valid tracks found in set: {set_id}"
            )

        return SoundCloudSet(
            id=str(set_id),
            title=set_title,
            artist=set_artist,
            tracks=tracks,
            artwork_url=set_artwork,
            permalink_url=data.get("webpage_url") or data.get("url"),
        )

    @staticmethod
    def _parse_duration(duration: Any) -> int:
        """Parse duration from yt-dlp output.

        Handles int (seconds) and string formats like "3:24" or "204".

        Args:
            duration: Duration value from yt-dlp JSON.

        Returns:
            Duration in seconds, or 0 if unparseable.
        """
        if duration is None:
            return 0
        if isinstance(duration, (int, float)):
            return int(duration)
        if isinstance(duration, str):
            # Try parsing as integer string
            try:
                return int(duration)
            except ValueError:
                pass
            # Try HH:MM:SS or MM:SS format
            parts = duration.split(":")
            if len(parts) == 2:
                try:
                    return int(parts[0]) * 60 + int(parts[1])
                except ValueError:
                    pass
            elif len(parts) == 3:
                try:
                    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                except ValueError:
                    pass
        return 0


# ============================================================================
# MUSICBRAINZ CLIENT
# ============================================================================


# Initialize musicbrainzngs once at module level
_mb_initialized = False

# Lazy import — musicbrainzngs is only needed when enrichment is used
musicbrainzngs: Any = None  # type: ignore[assignment]


def _ensure_mb_initialized() -> None:
    """Ensure musicbrainzngs is initialized with user agent and rate limit."""
    global _mb_initialized, musicbrainzngs
    if not _mb_initialized:
        import musicbrainzngs as _mb_mod

        musicbrainzngs = _mb_mod
        musicbrainzngs.set_useragent(
            "yubal", "0.8.0", "https://github.com/guillevc/yubal"
        )
        musicbrainzngs.set_rate_limit(1.0)
        _mb_initialized = True


class MusicBrainzClient:
    """MusicBrainz enrichment client.

    Searches MusicBrainz for canonical track metadata using the musicbrainzngs
    library. Used to enrich baseline metadata from SoundCloud (yt-dlp) with
    authoritative data: year, track number, album name, MBIDs.

    Implements MusicBrainzProtocol for dependency injection.

    Rate limiting: MusicBrainz allows 1 request/second. This client enforces
    that via ``mb.set_rate_limit(1.0)``. For bulk operations (sets with many
    tracks), callers should cache results and skip enrichment for large sets.
    """

    def __init__(self, config: MusicBrainzConfig | None = None) -> None:
        """Initialize the client.

        Args:
            config: MusicBrainz configuration. Uses defaults if not provided.
        """
        self._config = config or MusicBrainzConfig()
        _ensure_mb_initialized()

    def enrich_track(
        self,
        title: str,
        artists: list[str],
        duration_seconds: int,
    ) -> dict[str, Any] | None:
        """Search MusicBrainz for the best recording match.

        Search strategy:
        1. Search recordings with artist + title query
        2. Use the same fuzzy matching logic as YouTube Music matching
           (rapidfuzz, 70% threshold)
        3. If confident match: return MBID + metadata
        4. If no confident match: return None (caller uses baseline)

        Args:
            title: Track title.
            artists: List of artist names.
            duration_seconds: Track duration for additional validation.

        Returns:
            Dict with keys ``mbid``, ``release_mbid``, ``release_group_mbid``,
            ``year``, ``track_number``, ``total_tracks``, ``mb_title``,
            ``mb_artists``, ``mb_release_title``, ``duration_ms`` if a
            confident match found.
            Returns None if no confident match exists.
        """
        if not self._config.enabled or not title or not artists:
            return None

        # Build search query
        query = f"{title} {artists[0]}"
        logger.debug(
            "Searching MusicBrainz: %s (limit=%d)", query, self._config.search_limit
        )

        try:
            result = musicbrainzngs.search_recordings(
                query=query,
                artist=artists[0],
                recording=title,
                limit=self._config.search_limit,
            )
        except Exception as e:
            logger.warning("MusicBrainz search failed for '%s': %s", title, e)
            return None

        recording_list = result.get("recording-list", [])
        if not recording_list:
            return None

        # Find the best match using fuzzy matching
        best_match = self._find_best_match(
            title=title,
            artists=artists,
            duration_seconds=duration_seconds,
            recordings=recording_list,
        )

        if best_match is None:
            logger.debug(
                "No confident MusicBrainz match for '%s' by %s",
                title,
                "; ".join(artists),
            )
            return None

        # Extract metadata from the best match
        return self._extract_enrichment_data(best_match)

    def _find_best_match(
        self,
        title: str,
        artists: list[str],
        duration_seconds: int,
        recordings: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Find the best MusicBrainz recording match.

        Uses the same fuzzy matching logic as YouTube Music matching:
        1. Title similarity (rapidfuzz, 70% threshold)
        2. Artist similarity (best pairwise, 70% threshold)
        3. Duration validation (if available, within 15% tolerance)

        Args:
            title: Track title.
            artists: List of artist names.
            duration_seconds: Track duration for validation.
            recordings: List of recording dicts from MusicBrainz.

        Returns:
            Best matching recording dict, or None if no confident match.
        """
        from yubal.lib.matching import match_artists, match_title

        best: dict[str, Any] | None = None
        best_score = 0.0

        for recording in recordings:
            rec_title = recording.get("title", "")
            rec_length = recording.get("length")

            # Title match
            title_result = match_title(title, rec_title)
            if not title_result.is_good_match:
                continue

            # Artist match
            rec_artists = self._extract_artist_names(recording)
            if rec_artists:
                artist_result = match_artists(artists, rec_artists)
                if not artist_result.is_good_match:
                    continue

            # Duration validation (if both have it)
            score = title_result.similarity
            if duration_seconds and rec_length:
                try:
                    rec_duration = int(rec_length) / 1000  # MB stores ms
                    if rec_duration > 0:
                        duration_diff = abs(duration_seconds - rec_duration)
                        duration_ratio = duration_diff / duration_seconds
                        if duration_ratio > 0.15:  # >15% difference is suspicious
                            continue
                        # Slight bonus for close duration match
                        score = min(
                            100.0, score + (100.0 - duration_ratio * 100) * 0.1
                        )
                except (ValueError, TypeError):
                    pass

            if score > best_score:
                best_score = score
                best = recording

        if best and best_score < self._config.match_threshold:
            return None

        return best

    def _extract_artist_names(self, recording: dict[str, Any]) -> list[str]:
        """Extract artist names from a MusicBrainz recording.

        Key parsing note: artist-credit is always a list, not a dict.
        Access via artist_credit[0]["artist"]["name"].

        Args:
            recording: Recording dict from MusicBrainz.

        Returns:
            List of artist names.
        """
        artist_credit = recording.get("artist-credit") or []
        names: list[str] = []
        for ac in artist_credit:
            artist = ac.get("artist", {}) if isinstance(ac, dict) else {}
            name = artist.get("name", "")
            if name:
                names.append(name)
        return names

    def _extract_enrichment_data(
        self, recording: dict[str, Any]
    ) -> dict[str, Any]:
        """Extract enrichment metadata from a MusicBrainz recording.

        Args:
            recording: Recording dict from MusicBrainz.

        Returns:
            Dict with MBID, year, track_number, album info, etc.
        """
        mbid = recording.get("id", "")
        rec_length = recording.get("length")
        duration_ms = int(rec_length) if rec_length else 0

        # Artist names
        artists = self._extract_artist_names(recording)

        # Release info (first release in the list)
        release_list = recording.get("release-list") or []
        release = release_list[0] if release_list else {}

        release_mbid = release.get("id")
        release_title = release.get("title")
        release_date = release.get("date")
        year = release_date[:4] if release_date else None

        # Release group info
        rg = release.get("release-group") or {}
        release_group_mbid = rg.get("id")

        return {
            "mbid": mbid,
            "release_mbid": release_mbid,
            "release_group_mbid": release_group_mbid,
            "year": year,
            "track_number": None,
            "total_tracks": None,
            "mb_title": recording.get("title", ""),
            "mb_artists": artists,
            "mb_release_title": release_title,
            "duration_ms": duration_ms,
        }
