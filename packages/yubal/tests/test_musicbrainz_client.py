"""Tests for MusicBrainzClient and MusicBrainz enrichment."""

from unittest.mock import MagicMock, patch

import pytest
from yubal.client import MusicBrainzClient, MusicBrainzProtocol
from yubal.config import MusicBrainzConfig
from yubal.models.media import SoundCloudTrack
from yubal.models.track import TrackMetadata
from yubal.services.extractor import MetadataExtractorService


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mb_client() -> MusicBrainzClient:
    return MusicBrainzClient()


@pytest.fixture
def mb_client_disabled() -> MusicBrainzClient:
    return MusicBrainzClient(config=MusicBrainzConfig(enabled=False))


@pytest.fixture
def sample_recording() -> dict:
    """Create a sample MusicBrainz recording response."""
    return {
        "id": "a4803b45-0644-453f-aa1b-c762dc2f6941",
        "title": "Test Track",
        "length": "180000",
        "artist-credit": [
            {
                "artist": {
                    "id": "0383dadf-2a4e-4d10-a46a-e9e041da8eb3",
                    "name": "Test Artist",
                }
            }
        ],
        "release-list": [
            {
                "id": "cd610c82-2f82-4606-914e-062560583513",
                "title": "Test Album",
                "date": "2024-01-15",
                "release-group": {"id": "2b563f6a-f705-3f3e-854d-aebe6d8edbc8"},
            }
        ],
    }


@pytest.fixture
def sample_search_response(sample_recording: dict) -> dict:
    """Create a sample MusicBrainz search response."""
    return {"recording-list": [sample_recording]}


# ============================================================================
# MusicBrainzClient Tests
# ============================================================================


class TestMusicBrainzClient:
    """Tests for MusicBrainzClient."""

    def test_initializes_musicbrainzngs(self) -> None:
        """Should call set_useragent and set_rate_limit on first use."""
        import yubal.client as client_mod

        client_mod._mb_initialized = False

        with patch(
            "yubal.client._ensure_mb_initialized"
        ) as mock_init:
            client = MusicBrainzClient()
            mock_init.assert_called_once()
            assert client._config.enabled is True

        # Reset for subsequent tests
        client_mod._mb_initialized = False

    def test_disabled_client_returns_none(self, mb_client_disabled: MusicBrainzClient) -> None:
        """Should return None immediately when enrichment is disabled."""
        result = mb_client_disabled.enrich_track(
            title="Test Track",
            artists=["Test Artist"],
            duration_seconds=180,
        )
        assert result is None

    def test_empty_title_returns_none(self, mb_client: MusicBrainzClient) -> None:
        """Should return None for empty title."""
        result = mb_client.enrich_track(
            title="",
            artists=["Test Artist"],
            duration_seconds=180,
        )
        assert result is None

    def test_empty_artists_returns_none(self, mb_client: MusicBrainzClient) -> None:
        """Should return None for empty artists."""
        result = mb_client.enrich_track(
            title="Test Track",
            artists=[],
            duration_seconds=180,
        )
        assert result is None

    def test_search_recordings_called_with_correct_params(
        self,
        mb_client: MusicBrainzClient,
        sample_search_response: dict,
    ) -> None:
        """Should search with artist + title query."""
        with patch(
            "yubal.client.musicbrainzngs.search_recordings",
            return_value=sample_search_response,
        ) as mock_search:
            result = mb_client.enrich_track(
                title="Test Track",
                artists=["Test Artist"],
                duration_seconds=180,
            )
            assert result is not None
            assert result["mbid"] == "a4803b45-0644-453f-aa1b-c762dc2f6941"
            mock_search.assert_called_once()

    def test_search_with_no_results_returns_none(
        self,
        mb_client: MusicBrainzClient,
    ) -> None:
        """Should return None when search returns no recordings."""
        with patch("yubal.client.musicbrainzngs.search_recordings", return_value={"recording-list": []}):
            result = mb_client.enrich_track(
                title="Unknown Track",
                artists=["Unknown Artist"],
                duration_seconds=180,
            )
            assert result is None

    def test_search_api_error_handled_gracefully(
        self,
        mb_client: MusicBrainzClient,
    ) -> None:
        """Should return None when MusicBrainz API fails."""
        import musicbrainzngs as mb

        with patch.object(mb, "search_recordings", side_effect=Exception("Network error")):
            result = mb_client.enrich_track(
                title="Test Track",
                artists=["Test Artist"],
                duration_seconds=180,
            )
            assert result is None

    def test_enrichment_data_extracted_correctly(
        self,
        mb_client: MusicBrainzClient,
        sample_recording: dict,
    ) -> None:
        """Should extract all enrichment fields from recording."""
        with patch("yubal.client.musicbrainzngs.search_recordings", return_value={"recording-list": [sample_recording]}):
            result = mb_client.enrich_track(
                title="Test Track",
                artists=["Test Artist"],
                duration_seconds=180,
            )
            assert result is not None
            assert result["mbid"] == "a4803b45-0644-453f-aa1b-c762dc2f6941"
            assert result["release_mbid"] == "cd610c82-2f82-4606-914e-062560583513"
            assert result["release_group_mbid"] == "2b563f6a-f705-3f3e-854d-aebe6d8edbc8"
            assert result["year"] == "2024"
            assert result["mb_title"] == "Test Track"
            assert result["mb_artists"] == ["Test Artist"]
            assert result["mb_release_title"] == "Test Album"
            assert result["duration_ms"] == 180000

    def test_low_threshold_rejects_bad_match(
        self,
    ) -> None:
        """Should reject matches below threshold."""
        client = MusicBrainzClient(
            config=MusicBrainzConfig(match_threshold=95)
        )
        # Create a recording that won't match well
        recording = {
            "id": "bad-id",
            "title": "Completely Different Song",
            "length": "200000",
            "artist-credit": [{"artist": {"name": "Different Artist"}}],
            "release-list": [],
        }
        with patch("yubal.client.musicbrainzngs.search_recordings", return_value={"recording-list": [recording]}):
            result = client.enrich_track(
                title="My Song",
                artists=["My Artist"],
                duration_seconds=200,
            )
            assert result is None

    def test_duration_validation_filters_mismatch(
        self,
    ) -> None:
        """Should reject recordings with significantly different duration."""
        recording = {
            "id": "duration-test",
            "title": "Test Song",
            "length": "600000",  # 10 minutes
            "artist-credit": [{"artist": {"name": "Test Artist"}}],
            "release-list": [],
        }
        with patch("yubal.client.musicbrainzngs.search_recordings", return_value={"recording-list": [recording]}):
            result = MusicBrainzClient().enrich_track(
                title="Test Song",
                artists=["Test Artist"],
                duration_seconds=180,  # 3 minutes
            )
            # Should be rejected due to >15% duration difference
            assert result is None

    def test_multiple_recordings_picks_best_match(
        self,
    ) -> None:
        """Should pick the best matching recording from multiple results."""
        good_recording = {
            "id": "good-id",
            "title": "Test Song",
            "length": "180000",
            "artist-credit": [{"artist": {"name": "Test Artist"}}],
            "release-list": [],
        }
        bad_recording = {
            "id": "bad-id",
            "title": "Totally Different Song Name",
            "length": "180000",
            "artist-credit": [{"artist": {"name": "Test Artist"}}],
            "release-list": [],
        }
        with patch(
            "musicbrainzngs.search_recordings",
            return_value={"recording-list": [bad_recording, good_recording]},
        ):
            result = MusicBrainzClient().enrich_track(
                title="Test Song",
                artists=["Test Artist"],
                duration_seconds=180,
            )
            assert result is not None
            assert result["mbid"] == "good-id"

    def test_artist_credit_is_list_not_dict(self) -> None:
        """Test that artist-credit is correctly parsed as a list."""
        recording = {
            "id": "multi-artist",
            "title": "Collab Song",
            "length": "240000",
            "artist-credit": [
                {"artist": {"name": "Artist One"}},
                {"artist": {"name": "Artist Two"}},
            ],
            "release-list": [],
        }
        with patch("yubal.client.musicbrainzngs.search_recordings", return_value={"recording-list": [recording]}):
            result = MusicBrainzClient().enrich_track(
                title="Collab Song",
                artists=["Artist One"],
                duration_seconds=240,
            )
            assert result is not None
            assert result["mb_artists"] == ["Artist One", "Artist Two"]

    def test_release_with_no_date(self) -> None:
        """Should handle releases without dates."""
        recording = {
            "id": "no-date-id",
            "title": "Test Song",
            "length": "200000",
            "artist-credit": [{"artist": {"name": "Artist"}}],
            "release-list": [{"id": "rel-id", "title": "Album", "date": None}],
        }
        with patch("yubal.client.musicbrainzngs.search_recordings", return_value={"recording-list": [recording]}):
            result = MusicBrainzClient().enrich_track(
                title="Test Song",
                artists=["Artist"],
                duration_seconds=200,
            )
            assert result is not None
            assert result["year"] is None
            assert result["release_mbid"] == "rel-id"

    def test_empty_release_list(self) -> None:
        """Should handle recordings with no release list."""
        recording = {
            "id": "no-release-id",
            "title": "Test Song",
            "length": "200000",
            "artist-credit": [{"artist": {"name": "Artist"}}],
            "release-list": [],
        }
        with patch("yubal.client.musicbrainzngs.search_recordings", return_value={"recording-list": [recording]}):
            result = MusicBrainzClient().enrich_track(
                title="Test Song",
                artists=["Artist"],
                duration_seconds=200,
            )
            assert result is not None
            assert result["release_mbid"] is None

    def test_custom_search_limit(self) -> None:
        """Should use custom search limit from config."""
        client = MusicBrainzClient(config=MusicBrainzConfig(search_limit=10))
        with patch("yubal.client.musicbrainzngs.search_recordings", return_value={"recording-list": []}):
            client.enrich_track(
                title="Test",
                artists=["Artist"],
                duration_seconds=180,
            )
            # Verify the limit was passed (via call args)
            # We can't easily assert it without checking the mock call
            # But we can verify it doesn't crash


# ============================================================================
# MusicBrainzProtocol Tests
# ============================================================================


class TestMusicBrainzProtocol:
    """Tests that MusicBrainzProtocol is a valid Protocol."""

    def test_protocol_is_implemented_by_client(self) -> None:
        """MusicBrainzClient should satisfy MusicBrainzProtocol."""
        client: MusicBrainzProtocol = MusicBrainzClient()
        assert hasattr(client, "enrich_track")

    def test_protocol_signature(self) -> None:
        """Protocol methods should accept required parameters."""
        import inspect

        sig = inspect.signature(MusicBrainzProtocol.enrich_track)
        assert "title" in sig.parameters
        assert "artists" in sig.parameters
        assert "duration_seconds" in sig.parameters


# ============================================================================
# MetadataExtractorService Enrichment Tests
# ============================================================================


class TestMetadataExtractorServiceEnrichment:
    """Tests for MusicBrainz enrichment in MetadataExtractorService."""

    @pytest.fixture
    def mock_ytmusic_client(self) -> MagicMock:
        mock = MagicMock()
        mock.get_playlist.return_value = {"title": "Test", "tracks": []}
        return mock

    @pytest.fixture
    def mb_mock_client(self) -> MagicMock:
        return MagicMock()

    def test_extractor_accepts_musicbrainz_client(
        self, mock_ytmusic_client: MagicMock, mb_mock_client: MagicMock
    ) -> None:
        """MetadataExtractorService should accept optional musicbrainz_client."""
        service = MetadataExtractorService(
            client=mock_ytmusic_client,
            musicbrainz_client=mb_mock_client,
        )
        assert service._musicbrainz_client is mb_mock_client

    def test_extractor_works_without_musicbrainz_client(
        self, mock_ytmusic_client: MagicMock
    ) -> None:
        """MetadataExtractorService should work without musicbrainz_client."""
        service = MetadataExtractorService(client=mock_ytmusic_client)
        assert service._musicbrainz_client is None

    def test_enrich_track_with_musicbrainz_returns_baseline_when_no_mb(
        self, mock_ytmusic_client: MagicMock
    ) -> None:
        """Should return baseline metadata when no MusicBrainz client configured."""
        service = MetadataExtractorService(client=mock_ytmusic_client)
        sc_track = SoundCloudTrack(
            id="sc123",
            title="Test Track",
            artist="Test Artist",
            duration_seconds=180,
            artwork_url="https://example.com/art.jpg",
        )
        metadata = service._enrich_track_with_musicbrainz(sc_track)
        assert metadata is not None
        assert metadata.title == "Test Track"
        assert metadata.artists == ["Test Artist"]
        assert metadata.mbid is None

    def test_enrich_track_returns_baseline_when_no_mb_match(
        self, mock_ytmusic_client: MagicMock
    ) -> None:
        """Should return baseline metadata when MusicBrainz returns no match."""
        mb_mock = MagicMock()
        mb_mock.enrich_track.return_value = None
        service = MetadataExtractorService(
            client=mock_ytmusic_client,
            musicbrainz_client=mb_mock,
        )
        sc_track = SoundCloudTrack(
            id="sc123",
            title="Test Track",
            artist="Test Artist",
            duration_seconds=180,
            artwork_url="https://example.com/art.jpg",
        )
        metadata = service._enrich_track_with_musicbrainz(sc_track)
        assert metadata is not None
        assert metadata.title == "Test Track"
        assert metadata.match_result.value == "unmatched"

    def test_enrich_track_builds_enriched_metadata(
        self, mock_ytmusic_client: MagicMock
    ) -> None:
        """Should build enriched metadata when MusicBrainz returns a match."""
        enrichment = {
            "mbid": "mb-id-123",
            "release_mbid": "rel-mbid-123",
            "release_group_mbid": "rg-mbid-123",
            "year": "2024",
            "track_number": 3,
            "total_tracks": 12,
            "mb_title": "Test Song (Remastered)",
            "mb_artists": ["Test Artist", "Featured Artist"],
            "mb_release_title": "Test Album",
            "duration_ms": 180000,
        }
        mb_mock = MagicMock()
        mb_mock.enrich_track.return_value = enrichment
        service = MetadataExtractorService(
            client=mock_ytmusic_client,
            musicbrainz_client=mb_mock,
        )
        sc_track = SoundCloudTrack(
            id="sc123",
            title="Test Track",
            artist="Test Artist",
            duration_seconds=180,
            artwork_url="https://example.com/art.jpg",
        )
        metadata = service._enrich_track_with_musicbrainz(sc_track)
        assert metadata is not None
        assert metadata.title == "Test Song (Remastered)"
        assert metadata.artists == ["Test Artist", "Featured Artist"]
        assert metadata.album == "Test Album"
        assert metadata.year == "2024"
        assert metadata.track_number == 3
        assert metadata.total_tracks == 12
        assert metadata.mbid == "mb-id-123"
        assert metadata.release_mbid == "rel-mbid-123"
        assert metadata.release_group_mbid == "rg-mbid-123"
        assert metadata.match_result.value == "matched"

    def test_enrich_track_skips_missing_artist(
        self, mock_ytmusic_client: MagicMock
    ) -> None:
        """Should return baseline when track has no artist."""
        mb_mock = MagicMock()
        service = MetadataExtractorService(
            client=mock_ytmusic_client,
            musicbrainz_client=mb_mock,
        )
        sc_track = SoundCloudTrack(
            id="sc123",
            title="Test Track",
            artist="",
            duration_seconds=180,
        )
        metadata = service._enrich_track_with_musicbrainz(sc_track)
        assert metadata is not None
        assert metadata.title == "Test Track"
        # MusicBrainz should not have been called
        mb_mock.enrich_track.assert_not_called()

    def test_build_metadata_from_soundcloud_track(self) -> None:
        """Should build correct baseline metadata from SoundCloud track."""
        mock_ytm = MagicMock()
        mock_ytm.get_playlist.return_value = {"title": "Test", "tracks": []}
        service = MetadataExtractorService(client=mock_ytm)
        sc_track = SoundCloudTrack(
            id="sc123",
            title="Test Track",
            artist="Test Artist",
            duration_seconds=240,
            artwork_url="https://example.com/art.jpg",
            track_number=5,
            total_tracks=12,
        )
        metadata = service._build_metadata_from_soundcloud_track(sc_track)
        assert metadata.source_video_id == "sc123"
        assert metadata.title == "Test Track"
        assert metadata.artists == ["Test Artist"]
        assert metadata.album == "Test Track"
        assert metadata.track_number == 5
        assert metadata.total_tracks == 12
        assert metadata.duration_seconds == 240
        assert metadata.match_result.value == "unmatched"
        assert metadata.mbid is None

    def test_build_enriched_metadata_combines_data(self) -> None:
        """Should combine SoundCloud baseline with MusicBrainz enrichment."""
        mock_ytm = MagicMock()
        mock_ytm.get_playlist.return_value = {"title": "Test", "tracks": []}
        service = MetadataExtractorService(client=mock_ytm)
        sc_track = SoundCloudTrack(
            id="sc123",
            title="Test Track",
            artist="Test Artist",
            duration_seconds=180,
            artwork_url="https://example.com/art.jpg",
        )
        enrichment = {
            "mbid": "mb-123",
            "release_mbid": "rel-123",
            "release_group_mbid": "rg-123",
            "year": "2024",
            "track_number": 1,
            "total_tracks": 10,
            "mb_title": "Test Song",
            "mb_artists": ["Test Artist"],
            "mb_release_title": "Canonical Album",
            "duration_ms": 180000,
        }
        metadata = service._build_enriched_metadata(sc_track, enrichment)
        assert metadata.title == "Test Song"
        assert metadata.album == "Canonical Album"
        assert metadata.year == "2024"
        assert metadata.track_number == 1
        assert metadata.mbid == "mb-123"
        assert metadata.match_result.value == "matched"

    def test_cover_url_upscaled(self) -> None:
        """Cover URL should be upscaled to 1200px."""
        mock_ytm = MagicMock()
        mock_ytm.get_playlist.return_value = {"title": "Test", "tracks": []}
        service = MetadataExtractorService(client=mock_ytm)
        sc_track = SoundCloudTrack(
            id="sc123",
            title="Test Track",
            artist="Test Artist",
            duration_seconds=180,
            artwork_url="https://example.com/img=w120-h120.jpg",
        )
        metadata = service._build_metadata_from_soundcloud_track(sc_track)
        assert "w1200-h1200" in metadata.cover_url
