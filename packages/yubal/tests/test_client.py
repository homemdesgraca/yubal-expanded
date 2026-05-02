"""Tests for YTMusicClient."""

from unittest.mock import MagicMock

import pytest
from yubal.client import YTMusicClient
from yubal.exceptions import TrackNotFoundError, UpstreamAPIError

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_ytmusic() -> MagicMock:
    """Create a mock YTMusic instance."""
    return MagicMock()


@pytest.fixture
def sample_album_data() -> dict:
    """Create sample album API response data."""
    return {
        "title": "Test Album",
        "artists": [{"name": "Test Artist", "id": "artist123"}],
        "year": "2024",
        "thumbnails": [
            {"url": "https://example.com/thumb.jpg", "width": 544, "height": 544}
        ],
        "tracks": [
            {
                "videoId": "video123",
                "title": "Test Song",
                "artists": [{"name": "Test Artist", "id": "artist123"}],
                "trackNumber": 1,
                "duration_seconds": 240,
            }
        ],
    }


# ============================================================================
# Album Caching Tests
# ============================================================================


class TestAlbumCaching:
    """Tests for album caching in YTMusicClient."""

    def test_caches_album_on_first_fetch(
        self, mock_ytmusic: MagicMock, sample_album_data: dict
    ) -> None:
        """Should cache album after first fetch."""
        mock_ytmusic.get_album.return_value = sample_album_data
        client = YTMusicClient(ytmusic=mock_ytmusic)

        assert client.get_album_cache_size() == 0

        client.get_album("album123")

        assert client.get_album_cache_size() == 1

    def test_returns_cached_album_on_second_fetch(
        self, mock_ytmusic: MagicMock, sample_album_data: dict
    ) -> None:
        """Should return cached album without API call on second fetch."""
        mock_ytmusic.get_album.return_value = sample_album_data
        client = YTMusicClient(ytmusic=mock_ytmusic)

        # First fetch
        album1 = client.get_album("album123")
        # Second fetch
        album2 = client.get_album("album123")

        assert album1.title == album2.title
        # API should only be called once
        assert mock_ytmusic.get_album.call_count == 1

    def test_different_albums_cached_separately(
        self, mock_ytmusic: MagicMock, sample_album_data: dict
    ) -> None:
        """Should cache different albums separately."""
        album_data_2 = {
            **sample_album_data,
            "title": "Another Album",
        }
        mock_ytmusic.get_album.side_effect = [sample_album_data, album_data_2]
        client = YTMusicClient(ytmusic=mock_ytmusic)

        album1 = client.get_album("album123")
        album2 = client.get_album("album456")

        assert album1.title == "Test Album"
        assert album2.title == "Another Album"
        assert client.get_album_cache_size() == 2
        assert mock_ytmusic.get_album.call_count == 2

    def test_clear_album_cache(
        self, mock_ytmusic: MagicMock, sample_album_data: dict
    ) -> None:
        """Should clear all cached albums."""
        mock_ytmusic.get_album.return_value = sample_album_data
        client = YTMusicClient(ytmusic=mock_ytmusic)

        client.get_album("album123")
        assert client.get_album_cache_size() == 1

        client.clear_album_cache()
        assert client.get_album_cache_size() == 0

    def test_refetches_after_cache_clear(
        self, mock_ytmusic: MagicMock, sample_album_data: dict
    ) -> None:
        """Should refetch album after cache is cleared."""
        mock_ytmusic.get_album.return_value = sample_album_data
        client = YTMusicClient(ytmusic=mock_ytmusic)

        client.get_album("album123")
        client.clear_album_cache()
        client.get_album("album123")

        # API should be called twice (once before clear, once after)
        assert mock_ytmusic.get_album.call_count == 2

    def test_cache_is_per_client_instance(
        self, mock_ytmusic: MagicMock, sample_album_data: dict
    ) -> None:
        """Cache should be isolated per client instance."""
        mock_ytmusic.get_album.return_value = sample_album_data
        client1 = YTMusicClient(ytmusic=mock_ytmusic)
        client2 = YTMusicClient(ytmusic=mock_ytmusic)

        client1.get_album("album123")

        assert client1.get_album_cache_size() == 1
        assert client2.get_album_cache_size() == 0


# ============================================================================
# get_track() Tests
# ============================================================================


class TestGetTrack:
    def test_returns_playlist_track_for_valid_video_id(self) -> None:
        mock_ytm = MagicMock()
        mock_ytm.get_watch_playlist.return_value = {
            "tracks": [
                {
                    "videoId": "Vgpv5PtWsn4",
                    "title": "A COLD PLAY",
                    "artists": [{"name": "The Kid LAROI", "id": "UC123"}],
                    "album": {"name": "A COLD PLAY", "id": "MPREb_123"},
                    "videoType": "MUSIC_VIDEO_TYPE_ATV",
                    "thumbnails": [
                        {
                            "url": "https://example.com/thumb.jpg",
                            "width": 120,
                            "height": 120,
                        }
                    ],
                    "duration_seconds": 180,
                }
            ]
        }
        client = YTMusicClient(ytmusic=mock_ytm)
        track = client.get_track("Vgpv5PtWsn4")
        assert track.video_id == "Vgpv5PtWsn4"
        assert track.title == "A COLD PLAY"
        mock_ytm.get_watch_playlist.assert_called_once_with("Vgpv5PtWsn4")

    def test_raises_for_empty_video_id(self) -> None:
        client = YTMusicClient(ytmusic=MagicMock())
        with pytest.raises(ValueError, match="video_id cannot be empty"):
            client.get_track("")

    def test_raises_track_not_found_for_empty_tracks(self) -> None:
        mock_ytm = MagicMock()
        mock_ytm.get_watch_playlist.return_value = {"tracks": []}
        client = YTMusicClient(ytmusic=mock_ytm)
        with pytest.raises(TrackNotFoundError, match="Track not found"):
            client.get_track("invalid123")

    def test_raises_track_not_found_for_none_tracks(self) -> None:
        mock_ytm = MagicMock()
        mock_ytm.get_watch_playlist.return_value = {"tracks": None}
        client = YTMusicClient(ytmusic=mock_ytm)
        with pytest.raises(TrackNotFoundError, match="Track not found"):
            client.get_track("invalid123")

    def test_raises_api_error_on_exception(self) -> None:
        from ytmusicapi.exceptions import YTMusicServerError

        mock_ytm = MagicMock()
        mock_ytm.get_watch_playlist.side_effect = YTMusicServerError("API failure")
        client = YTMusicClient(ytmusic=mock_ytm)
        with pytest.raises(UpstreamAPIError, match="Failed to fetch track"):
            client.get_track("abc123")

    def test_normalizes_watch_playlist_response_format(self) -> None:
        """Should normalize thumbnail->thumbnails and length->duration_seconds."""
        mock_ytm = MagicMock()
        mock_ytm.get_watch_playlist.return_value = {
            "tracks": [
                {
                    "videoId": "Vgpv5PtWsn4",
                    "title": "A COLD PLAY",
                    "artists": [{"name": "The Kid LAROI", "id": "UC123"}],
                    "album": {"name": "A COLD PLAY", "id": "MPREb_123"},
                    "videoType": "MUSIC_VIDEO_TYPE_ATV",
                    "thumbnail": [
                        {
                            "url": "https://example.com/thumb.jpg",
                            "width": 544,
                            "height": 544,
                        }
                    ],
                    "length": "3:00",
                }
            ]
        }
        client = YTMusicClient(ytmusic=mock_ytm)
        track = client.get_track("Vgpv5PtWsn4")
        assert track.video_id == "Vgpv5PtWsn4"
        assert track.duration_seconds == 180
        assert len(track.thumbnails) == 1
        assert track.thumbnails[0].url == "https://example.com/thumb.jpg"


# ============================================================================
# SoundCloudClient Tests
# ============================================================================


import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from yubal.client import SoundCloudClient, SoundCloudProtocol
from yubal.exceptions import SoundCloudParseError, SoundCloudUnavailableError
from yubal.models.media import SoundCloudSet, SoundCloudTrack


class TestSoundCloudClient:
    """Tests for SoundCloudClient."""

    @pytest.fixture
    def client(self) -> SoundCloudClient:
        return SoundCloudClient()

    # ---- _run_dump_json ----

    def test_run_dump_json_calls_ytdlp(self, client: SoundCloudClient) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"id": "12345", "title": "Test Track"})
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            client._run_dump_json("https://soundcloud.com/artist/track")
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "yt-dlp" in call_args[0]
            assert "--dump-json" in call_args
            assert "--no-download" in call_args
            assert "--no-warnings" in call_args

    def test_run_dump_json_raises_for_file_not_found(self, client: SoundCloudClient) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError()):
            with pytest.raises(SoundCloudParseError, match="yt-dlp is not installed"):
                client._run_dump_json("https://soundcloud.com/artist/track")

    def test_run_dump_json_raises_for_timeout(self, client: SoundCloudClient) -> None:
        import subprocess as sp

        with patch("subprocess.run", side_effect=sp.TimeoutExpired("yt-dlp", 30)):
            with pytest.raises(SoundCloudParseError, match="timed out"):
                client._run_dump_json("https://soundcloud.com/artist/track")

    def test_run_dump_json_raises_for_unavailable_track(self, client: SoundCloudClient) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "This track is no longer available on SoundCloud"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(SoundCloudUnavailableError, match="unavailable"):
                client._run_dump_json("https://soundcloud.com/artist/track")

    def test_run_dump_json_raises_for_private_track(self, client: SoundCloudClient) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "This content is private"

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(SoundCloudUnavailableError, match="unavailable"):
                client._run_dump_json("https://soundcloud.com/artist/track")

    def test_run_dump_json_raises_for_non_json_output(self, client: SoundCloudClient) -> None:
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "not valid json {{{"
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result):
            with pytest.raises(SoundCloudParseError, match="not valid JSON"):
                client._run_dump_json("https://soundcloud.com/artist/track")

    # ---- get_track ----

    def test_get_track_parses_basic_fields(self, client: SoundCloudClient) -> None:
        data = {
            "id": "123456789",
            "title": "Test Track",
            "duration": 240,
            "uploader": "Test Artist",
            "webpage_url": "https://soundcloud.com/artist/track",
        }

        with patch.object(client, "_run_dump_json", return_value=data):
            track = client.get_track("https://soundcloud.com/artist/track")

        assert track.id == "123456789"
        assert track.title == "Test Track"
        assert track.artist == "Test Artist"
        assert track.duration_seconds == 240
        assert track.permalink_url == "https://soundcloud.com/artist/track"

    def test_get_track_parses_dict_uploader(self, client: SoundCloudClient) -> None:
        data = {
            "id": "123456789",
            "title": "Test Track",
            "duration": 180,
            "uploader": {"title": "Dict Artist", "id": "SC123"},
            "webpage_url": "https://soundcloud.com/artist/track",
        }

        with patch.object(client, "_run_dump_json", return_value=data):
            track = client.get_track("https://soundcloud.com/artist/track")

        assert track.artist == "Dict Artist"

    def test_get_track_parses_duration_string(self, client: SoundCloudClient) -> None:
        data = {
            "id": "123456789",
            "title": "Test Track",
            "duration_string": "4:30",
            "uploader": "Artist",
            "webpage_url": "https://soundcloud.com/artist/track",
        }

        with patch.object(client, "_run_dump_json", return_value=data):
            track = client.get_track("https://soundcloud.com/artist/track")

        assert track.duration_seconds == 270

    def test_get_track_parses_artwork_url(self, client: SoundCloudClient) -> None:
        data = {
            "id": "123456789",
            "title": "Test Track",
            "duration": 180,
            "uploader": "Artist",
            "thumbnails": [
                {"url": "https://example.com/small.jpg", "width": 120, "height": 120},
                {"url": "https://example.com/large.jpg", "width": 500, "height": 500},
            ],
            "webpage_url": "https://soundcloud.com/artist/track",
        }

        with patch.object(client, "_run_dump_json", return_value=data):
            track = client.get_track("https://soundcloud.com/artist/track")

        assert track.artwork_url == "https://example.com/large.jpg"

    def test_get_track_handles_missing_artwork(self, client: SoundCloudClient) -> None:
        data = {
            "id": "123456789",
            "title": "Test Track",
            "duration": 180,
            "uploader": "Artist",
            "webpage_url": "https://soundcloud.com/artist/track",
        }

        with patch.object(client, "_run_dump_json", return_value=data):
            track = client.get_track("https://soundcloud.com/artist/track")

        assert track.artwork_url is None

    def test_get_track_raises_for_missing_id(self, client: SoundCloudClient) -> None:
        data = {"title": "Test Track"}

        with patch.object(client, "_run_dump_json", return_value=data):
            with pytest.raises(SoundCloudParseError, match="Missing track ID"):
                client.get_track("https://soundcloud.com/artist/track")

    def test_get_track_raises_for_missing_title(self, client: SoundCloudClient) -> None:
        data = {"id": "123456789"}

        with patch.object(client, "_run_dump_json", return_value=data):
            with pytest.raises(SoundCloudParseError, match="Missing title"):
                client.get_track("https://soundcloud.com/artist/track")

    def test_get_track_has_valid_metadata(self, client: SoundCloudClient) -> None:
        data = {
            "id": "123456789",
            "title": "Test Track",
            "duration": 180,
            "uploader": "Artist",
            "webpage_url": "https://soundcloud.com/artist/track",
        }

        with patch.object(client, "_run_dump_json", return_value=data):
            track = client.get_track("https://soundcloud.com/artist/track")

        assert track.has_valid_metadata is True

    def test_get_track_invalid_metadata_no_artist(self, client: SoundCloudClient) -> None:
        data = {
            "id": "123456789",
            "title": "Test Track",
            "duration": 180,
            "uploader": "",
            "webpage_url": "https://soundcloud.com/artist/track",
        }

        with patch.object(client, "_run_dump_json", return_value=data):
            track = client.get_track("https://soundcloud.com/artist/track")

        assert track.has_valid_metadata is False

    def test_get_track_invalid_metadata_no_duration(self, client: SoundCloudClient) -> None:
        data = {
            "id": "123456789",
            "title": "Test Track",
            "duration": 0,
            "uploader": "Artist",
            "webpage_url": "https://soundcloud.com/artist/track",
        }

        with patch.object(client, "_run_dump_json", return_value=data):
            track = client.get_track("https://soundcloud.com/artist/track")

        assert track.has_valid_metadata is False

    # ---- get_set ----

    def test_get_set_parses_video_list(self, client: SoundCloudClient) -> None:
        data = {
            "_type": "video_list",
            "id": "set123",
            "title": "Test Set",
            "uploader": "Set Artist",
            "track_count": 3,
            "entries": [
                {
                    "id": "t1",
                    "title": "Track One",
                    "duration": 180,
                    "uploader": "Set Artist",
                    "track": 1,
                },
                {
                    "id": "t2",
                    "title": "Track Two",
                    "duration": 240,
                    "uploader": "Set Artist",
                    "track": 2,
                },
                {
                    "id": "t3",
                    "title": "Track Three",
                    "duration": 200,
                    "uploader": "Set Artist",
                    "track": 3,
                },
            ],
        }

        with patch.object(client, "_run_dump_json", return_value=data):
            set_data = client.get_set("https://soundcloud.com/artist/sets/test")

        assert set_data.id == "set123"
        assert set_data.title == "Test Set"
        assert set_data.artist == "Set Artist"
        assert len(set_data.tracks) == 3
        assert set_data.tracks[0].track_number == 1
        assert set_data.tracks[0].total_tracks == 3
        assert set_data.tracks[1].title == "Track Two"

    def test_get_set_skips_malformed_entries(self, client: SoundCloudClient) -> None:
        data = {
            "_type": "video_list",
            "id": "set123",
            "title": "Test Set",
            "uploader": "Set Artist",
            "entries": [
                {"id": "t1", "title": "Track One", "duration": 180, "uploader": "Set Artist"},
                {"id": "", "title": "Bad Track"},  # Missing ID -> parse error
                {"id": "t3", "title": "Track Three", "duration": 200, "uploader": "Set Artist"},
            ],
        }

        with patch.object(client, "_run_dump_json", return_value=data):
            set_data = client.get_set("https://soundcloud.com/artist/sets/test")

        assert len(set_data.tracks) == 2
        assert set_data.tracks[0].id == "t1"
        assert set_data.tracks[1].id == "t3"

    def test_get_set_raises_when_no_valid_tracks(self, client: SoundCloudClient) -> None:
        data = {
            "_type": "video_list",
            "id": "set123",
            "title": "Test Set",
            "entries": [
                {"title": "No ID"},
            ],
        }

        with patch.object(client, "_run_dump_json", return_value=data):
            with pytest.raises(SoundCloudParseError, match="No valid tracks"):
                client.get_set("https://soundcloud.com/artist/sets/test")

    def test_get_set_wraps_single_track(self, client: SoundCloudClient) -> None:
        """If a single track URL is passed to get_set, it should wrap it."""
        data = {
            "id": "t1",
            "title": "Single Track",
            "duration": 180,
            "uploader": "Artist",
            "webpage_url": "https://soundcloud.com/artist/track",
        }

        with patch.object(client, "_run_dump_json", return_value=data):
            set_data = client.get_set("https://soundcloud.com/artist/track")

        assert set_data.id == "t1"
        assert len(set_data.tracks) == 1
        assert set_data.tracks[0].title == "Single Track"

    def test_get_set_uses_default_track_number(self, client: SoundCloudClient) -> None:
        data = {
            "_type": "video_list",
            "id": "set123",
            "title": "Test Set",
            "entries": [
                {"id": "t1", "title": "Track One", "duration": 180, "uploader": "Artist"},
                {"id": "t2", "title": "Track Two", "duration": 240, "uploader": "Artist"},
            ],
        }

        with patch.object(client, "_run_dump_json", return_value=data):
            set_data = client.get_set("https://soundcloud.com/artist/sets/test")

        assert set_data.tracks[0].track_number == 1
        assert set_data.tracks[1].track_number == 2
        assert set_data.tracks[0].total_tracks == 2

    # ---- _parse_duration ----

    def test_parse_duration_int(self) -> None:
        assert SoundCloudClient._parse_duration(180) == 180

    def test_parse_duration_string_int(self) -> None:
        assert SoundCloudClient._parse_duration("240") == 240

    def test_parse_duration_mm_ss(self) -> None:
        assert SoundCloudClient._parse_duration("3:24") == 204

    def test_parse_duration_hh_mm_ss(self) -> None:
        assert SoundCloudClient._parse_duration("1:02:30") == 3750

    def test_parse_duration_none(self) -> None:
        assert SoundCloudClient._parse_duration(None) == 0

    def test_parse_duration_unparseable(self) -> None:
        assert SoundCloudClient._parse_duration("invalid") == 0

    def test_parse_duration_float(self) -> None:
        assert SoundCloudClient._parse_duration(180.7) == 180

    # ---- Custom yt-dlp path ----

    def test_custom_ytdlp_path(self) -> None:
        client = SoundCloudClient(yt_dlp_path="/custom/yt-dlp")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = json.dumps({"id": "1", "title": "Test"})
        mock_result.stderr = ""

        with patch("subprocess.run", return_value=mock_result) as mock_run:
            client.get_track("https://soundcloud.com/artist/track")
            cmd = mock_run.call_args[0][0]
            assert cmd[0] == "/custom/yt-dlp"


class TestSoundCloudProtocol:
    """Tests that SoundCloudProtocol is a valid Protocol."""

    def test_protocol_is_implemented_by_client(self) -> None:
        """SoundCloudClient should satisfy SoundCloudProtocol."""
        client: SoundCloudProtocol = SoundCloudClient()
        assert hasattr(client, "get_track")
        assert hasattr(client, "get_set")

    def test_protocol_signature(self) -> None:
        """Protocol methods should accept string URLs."""
        import inspect

        sig_track = inspect.signature(SoundCloudProtocol.get_track)
        assert "url" in sig_track.parameters

        sig_set = inspect.signature(SoundCloudProtocol.get_set)
        assert "url" in sig_set.parameters
        mock_ytm = MagicMock()
        mock_ytm.get_playlist.return_value = {
            "title": "Liked Music",
            "tracks": [
                {
                    "videoId": "abc123",
                    "videoType": "MUSIC_VIDEO_TYPE_ATV",
                    "title": "Track With Null Artists",
                    "artists": None,
                    "thumbnails": [
                        {
                            "url": "https://example.com/thumb.jpg",
                            "width": 120,
                            "height": 120,
                        }
                    ],
                    "duration_seconds": 180,
                }
            ],
        }

        client = YTMusicClient(ytmusic=mock_ytm)

        playlist = client.get_playlist("LM")

        assert len(playlist.tracks) == 1
        assert playlist.tracks[0].artists == []
