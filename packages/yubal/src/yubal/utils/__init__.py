"""Utility functions for yubal.

Available via `from yubal.utils import ...` for power users.
Not re-exported at the top-level `yubal` package.
"""

from yubal.utils.cleanup import cleanup_part_files
from yubal.utils.cookies import cookies_to_ytmusic_auth, is_authenticated_cookies
from yubal.utils.coverartarchive import (
    fetch_cover_from_caa,
    fetch_cover_from_release_group_mbid,
    fetch_cover_from_release_mbid,
    get_cover_url_from_caa,
)
from yubal.utils.cover import (
    clear_cover_cache,
    fetch_cover,
    get_cover_cache_size,
    write_playlist_cover,
)
from yubal.utils.filename import (
    build_track_path,
    clean_filename,
    format_playlist_filename,
)
from yubal.utils.url import is_single_track_url, parse_playlist_id, parse_video_id

__all__ = [
    "build_track_path",
    "clean_filename",
    "cleanup_part_files",
    "clear_cover_cache",
    "cookies_to_ytmusic_auth",
    "fetch_cover",
    "fetch_cover_from_caa",
    "fetch_cover_from_release_group_mbid",
    "fetch_cover_from_release_mbid",
    "format_playlist_filename",
    "get_cover_cache_size",
    "get_cover_url_from_caa",
    "is_authenticated_cookies",
    "is_single_track_url",
    "parse_playlist_id",
    "parse_video_id",
    "write_playlist_cover",
]
