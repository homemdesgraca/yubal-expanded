"""YouTube Music API client wrapper."""

import json
import logging
import re
import shutil
import subprocess
from collections import OrderedDict
from pathlib import Path
from typing import Any, Protocol, cast

from ytmusicapi import YTMusic
from ytmusicapi.exceptions import YTMusicError, YTMusicServerError, YTMusicUserError

from yubal.config import APIConfig
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
        try:
            return json.loads(stdout)
        except json.JSONDecodeError as e:
            raise SoundCloudParseError(
                f"yt-dlp output is not valid JSON: {e}"
            )

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
        JSON output. For sets, yt-dlp returns a ``_type": "video_list"``
        entry with ``entries`` containing all tracks in the set.

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
