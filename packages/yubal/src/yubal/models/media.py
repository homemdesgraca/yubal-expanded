"""Models for parsing ytmusicapi responses.

These are internal models used to parse and validate responses from
the YouTube Music API. They may change if the API changes.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Album",
    "AlbumRef",
    "AlbumTrack",
    "Artist",
    "Playlist",
    "PlaylistTrack",
    "SearchResult",
    "SoundCloudSet",
    "SoundCloudTrack",
    "Thumbnail",
]


class YTMusicModel(BaseModel):
    """Base model for ytmusicapi responses."""

    model_config = ConfigDict(extra="ignore", frozen=True)


class Thumbnail(YTMusicModel):
    """Video/album thumbnail."""

    url: str
    width: int
    height: int


class Artist(YTMusicModel):
    """Artist reference."""

    name: str
    id: str | None = None


class AlbumRef(YTMusicModel):
    """Album reference (in playlist/search results)."""

    id: str | None = None
    name: str


class PlaylistTrack(YTMusicModel):
    """Track in a playlist."""

    video_id: str = Field(alias="videoId")
    video_type: str | None = Field(default=None, alias="videoType")
    title: str
    artists: list[Artist] = Field(default_factory=list)
    album: AlbumRef | None = None
    thumbnails: list[Thumbnail] = Field(default_factory=list)
    duration_seconds: int


class Playlist(YTMusicModel):
    """Playlist response from get_playlist()."""

    title: str | None = None
    thumbnails: list[Thumbnail] = Field(default_factory=list)
    tracks: list[PlaylistTrack]
    unavailable_tracks_raw: list[dict[str, Any]] = Field(
        default_factory=list, alias="unavailable_tracks"
    )
    author: Artist | None = None  # Channel/creator name
    year: str | None = None

    @property
    def unavailable_count(self) -> int:
        """Number of unavailable tracks in the playlist."""
        return len(self.unavailable_tracks_raw)


class AlbumTrack(YTMusicModel):
    """Track in an album."""

    video_id: str = Field(alias="videoId")
    title: str
    artists: list[Artist] = Field(default_factory=list)
    track_number: int = Field(alias="trackNumber")
    duration_seconds: int


class Album(YTMusicModel):
    """Album response from get_album()."""

    title: str
    artists: list[Artist]
    year: str | None = None
    thumbnails: list[Thumbnail]
    tracks: list[AlbumTrack]


class SearchResult(YTMusicModel):
    """Song search result."""

    video_id: str = Field(alias="videoId")
    video_type: str | None = Field(default=None, alias="videoType")
    title: str
    artists: list[Artist] = Field(default_factory=list)
    album: AlbumRef | None = None


# ============================================================================
# SOUND CLOUD MODELS
# ============================================================================


class SoundCloudTrack(YTMusicModel):
    """Metadata for a single SoundCloud track.

    Parsed from yt-dlp --dump-json output for SoundCloud URLs.
    Contains the minimal fields needed for yubal's extraction pipeline.

    Attributes:
        id: SoundCloud track ID (numeric string).
        title: Track title.
        artist: Artist name (may be empty for tracks without artist).
        duration_seconds: Track duration in seconds (0 if unavailable).
        artwork_url: URL to the track's artwork image (may be None).
        permalink_url: Permanent URL to the track on SoundCloud.
        track_number: Track position within a set (None for standalone tracks).
        total_tracks: Total tracks in the set (None for standalone tracks).
        upload_date: Upload date from yt-dlp (YYYYMMDD format, may be None).
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str
    title: str
    artist: str = ""
    duration_seconds: int = 0
    artwork_url: str | None = None
    permalink_url: str | None = None
    track_number: int | None = None
    total_tracks: int | None = None
    upload_date: str | None = None  # YYYYMMDD format from yt-dlp

    @property
    def has_valid_metadata(self) -> bool:
        """Check if the track has the minimum required metadata."""
        return bool(self.title and self.artist and self.duration_seconds > 0)


class SoundCloudSet(YTMusicModel):
    """A SoundCloud set (playlist) containing multiple tracks.

    Parsed from yt-dlp --dump-json output for SoundCloud set URLs.

    Attributes:
        id: SoundCloud set ID.
        title: Set title/name.
        artist: Set creator/artist name.
        tracks: List of tracks in the set.
        artwork_url: URL to the set's cover image (may be None).
        permalink_url: Permanent URL to the set on SoundCloud.
    """

    model_config = ConfigDict(extra="ignore", frozen=True)

    id: str
    title: str
    artist: str = ""
    tracks: list[SoundCloudTrack]
    artwork_url: str | None = None
    permalink_url: str | None = None
