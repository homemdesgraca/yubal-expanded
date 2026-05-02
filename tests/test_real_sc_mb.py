"""Real-world integration tests for SoundCloud + MusicBrainz enrichment.

These tests hit actual SoundCloud and MusicBrainz APIs.
Run with: uv run pytest packages/yubal/tests/test_real_sc_mb.py -v
"""

import pytest


# ============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def sc_client() -> "SoundCloudClient":
    from yubal.client import SoundCloudClient

    return SoundCloudClient()


@pytest.fixture
def mb_client() -> "MusicBrainzClient":
    from yubal.client import MusicBrainzClient

    return MusicBrainzClient()


@pytest.fixture
def mock_ytmusic_client() -> "MagicMock":
    from unittest.mock import MagicMock

    mock = MagicMock()
    mock.get_playlist.return_value = {"title": "Test", "tracks": []}
    return mock


# ============================================================================
# SoundCloud Track Extraction
# ============================================================================


class TestRealSoundCloudTrack:
    """Test extracting metadata from a real SoundCloud track."""

    def test_jane_remover_psychoboost(self, sc_client: "SoundCloudClient") -> None:
        """Extract metadata from Jane Remover - Psychoboost ft Danny Brown."""
        track = sc_client.get_track(
            "https://soundcloud.com/janeremover/psychoboost-ft-danny-brown"
        )

        assert track.id == "2067874952"
        assert "Psychoboost" in track.title
        assert "Jane Remover" == track.artist
        assert track.duration_seconds > 0
        assert track.artwork_url is not None
        assert track.permalink_url is not None
        assert track.has_valid_metadata is True

    def test_track_artwork_is_upscaled(self) -> None:
        """Cover art URLs from SoundCloud should be upscalable to 1200px."""
        from yubal.services.extractor import _upscale_thumbnail_url

        # SoundCloud format: t500x500 -> t1200x1200
        url = "https://i1.sndcdn.com/artworks-dNyo0pXBiwtMYxPA-tHMSzQ-t500x500.jpg"
        result = _upscale_thumbnail_url(url, 1200)
        assert "t1200x1200" in result

        # Google/YouTube format: =w120-h120 -> =w1200-h1200
        url2 = "https://lh3.googleusercontent.com/abc=w120-h120-l90-rj"
        result2 = _upscale_thumbnail_url(url2, 1200)
        assert "w1200-h1200" in result2


# ============================================================================
# MusicBrainz Enrichment
# ============================================================================


class TestRealMusicBrainzEnrichment:
    """Test MusicBrainz enrichment against real data."""

    def test_jane_remover_psychoboost_enrichment(
        self, mb_client: "MusicBrainzClient"
    ) -> None:
        """Enrich Jane Remover - Psychoboost ft Danny Brown with MusicBrainz.

        The title normalization strips "ft danny brown" so the match
        against MB's "Psychoboost" succeeds.
        """
        result = mb_client.enrich_track(
            title="Psychoboost ft danny brown",
            artists=["Jane Remover"],
            duration_seconds=244,
        )

        assert result is not None
        assert result["mbid"] == "0ba469ff-a111-4cfa-9db0-fb23667d9c42"
        assert result["mb_title"] == "Psychoboost"
        assert "Jane Remover" in result["mb_artists"]
        assert "Danny Brown" in result["mb_artists"]
        assert result["mb_release_title"] == "Revengeseekerz"
        assert result["year"] == "2025"

    def test_jane_remover_psychoboost_fallback_to_baseline(
        self,
        sc_client: "SoundCloudClient",
        mb_client: "MusicBrainzClient",
        mock_ytmusic_client: "MagicMock",
    ) -> None:
        """If MB doesn't match, extractor should fall back to SoundCloud baseline."""
        from unittest.mock import MagicMock

        # Force MB to return no match
        mb_mock = MagicMock()
        mb_mock.enrich_track.return_value = None

        from yubal.services.extractor import MetadataExtractorService

        service = MetadataExtractorService(
            client=mock_ytmusic_client,
            musicbrainz_client=mb_mock,
        )

        # Get real track from SoundCloud
        sc_track = sc_client.get_track(
            "https://soundcloud.com/janeremover/psychoboost-ft-danny-brown"
        )

        # Enrich (should fall back to baseline since MB returns None)
        metadata = service._enrich_track_with_musicbrainz(sc_track)

        assert metadata is not None
        assert metadata.title == sc_track.title
        assert metadata.artists == [sc_track.artist]
        assert metadata.mbid is None  # No MB match
        assert metadata.match_result.value == "unmatched"

    def test_extractor_full_pipeline_with_real_sc_and_mock_mb(
        self,
        sc_client: "SoundCloudClient",
        mb_client: "MusicBrainzClient",
        mock_ytmusic_client: "MagicMock",
    ) -> None:
        """Full pipeline: SoundCloud track -> MB enrichment -> TrackMetadata."""
        from unittest.mock import MagicMock

        # Real SoundCloud track
        sc_track = sc_client.get_track(
            "https://soundcloud.com/janeremover/psychoboost-ft-danny-brown"
        )

        # Real MB enrichment
        mb_result = mb_client.enrich_track(
            title=sc_track.title,
            artists=[sc_track.artist],
            duration_seconds=sc_track.duration_seconds,
        )

        # Build enriched metadata
        from yubal.services.extractor import MetadataExtractorService

        service = MetadataExtractorService(client=mock_ytmusic_client)

        if mb_result:
            metadata = service._build_enriched_metadata(sc_track, mb_result)
            assert metadata.match_result.value == "matched"
            assert metadata.mbid is not None
            assert metadata.year is not None or mb_result.get("year") is not None
            print(f"\nEnriched: {metadata.title} by {metadata.artists}")
            print(f"  Album: {metadata.album}")
            print(f"  Year: {metadata.year}")
            print(f"  MBID: {metadata.mbid}")
        else:
            # Fallback to baseline
            metadata = service._build_metadata_from_soundcloud_track(sc_track)
            assert metadata.match_result.value == "unmatched"
            assert metadata.mbid is None
            print(f"\nBaseline: {metadata.title} by {metadata.artists}")
            print(f"  Album: {metadata.album}")
            print(f"  Year: {metadata.year}")


# ============================================================================
# SoundCloud Set Extraction
# ============================================================================


class TestRealSoundCloudSet:
    """Test extracting metadata from a real SoundCloud set."""

    def test_jane_remover_revengeseekerz_set(
        self, sc_client: "SoundCloudClient"
    ) -> None:
        """Extract all tracks from Jane Remover - Revengeseekerz set."""
        set_data = sc_client.get_set(
            "https://soundcloud.com/janeremover/sets/revengeseekerz"
        )

        assert set_data.id is not None
        assert "Revengeseekerz" in set_data.title
        assert set_data.artist == "Jane Remover"
        assert len(set_data.tracks) > 0

        # All tracks should have valid metadata
        for i, track in enumerate(set_data.tracks):
            assert track.id is not None
            assert track.title is not None
            assert track.artist is not None
            assert track.duration_seconds > 0, f"Track {i+1} has no duration"
            assert track.has_valid_metadata is True, (
                f"Track {i+1} ({track.title}) has invalid metadata"
            )
            print(
                f"  Track {track.track_number}: {track.title} "
                f"({track.duration_seconds}s)"
            )

        # Verify track numbers are sequential
        track_numbers = [t.track_number for t in set_data.tracks]
        assert track_numbers == list(range(1, len(set_data.tracks) + 1))

    def test_set_tracks_enriched_with_musicbrainz(
        self,
        sc_client: "SoundCloudClient",
        mb_client: "MusicBrainzClient",
        mock_ytmusic_client: "MagicMock",
    ) -> None:
        """Test MB enrichment for each track in the set."""
        from unittest.mock import MagicMock

        set_data = sc_client.get_set(
            "https://soundcloud.com/janeremover/sets/revengeseekerz"
        )

        from yubal.services.extractor import MetadataExtractorService

        service = MetadataExtractorService(client=mock_ytmusic_client)

        enriched_count = 0
        baseline_count = 0

        for track in set_data.tracks[:5]:  # Test first 5 tracks
            # Try MB enrichment
            mb_result = mb_client.enrich_track(
                title=track.title,
                artists=[track.artist],
                duration_seconds=track.duration_seconds,
            )

            if mb_result:
                metadata = service._build_enriched_metadata(track, mb_result)
                enriched_count += 1
                print(
                    f"  ENRICHED: {track.title} -> {metadata.album} "
                    f"(year={metadata.year}, mbid={metadata.mbid[:8]}...)"
                )
            else:
                metadata = service._build_metadata_from_soundcloud_track(track)
                baseline_count += 1
                print(f"  BASELINE: {track.title} (no MB match)")

            assert metadata is not None
            assert metadata.title is not None
            assert len(metadata.artists) > 0

        print(f"\nSummary: {enriched_count} enriched, {baseline_count} baseline")


# ============================================================================
# Duration Matching
# ============================================================================


class TestDurationMatching:
    """Test that duration validation works correctly with real data."""

    def test_duration_within_tolerance(self, mb_client: "MusicBrainzClient") -> None:
        """Tracks with similar duration should match."""
        result = mb_client.enrich_track(
            title="Psychoboost ft danny brown",
            artists=["Jane Remover"],
            duration_seconds=244,
        )
        # If MB has it, duration should be within ~15%
        if result:
            mb_duration_s = result["duration_ms"] / 1000
            diff = abs(244 - mb_duration_s)
            ratio = diff / 244
            print(
                f"Duration match: SC={244}s, MB={mb_duration_s}s, "
                f"diff={ratio:.1%}"
            )
            assert ratio <= 0.15, f"Duration diff too large: {ratio:.1%}"

    def test_duration_outside_tolerance_rejected(self) -> None:
        """Tracks with very different duration should be rejected."""
        from unittest.mock import MagicMock

        import yubal.client as cm

        recording = {
            "id": "test-id",
            "title": "Test Song",
            "length": "600000",  # 10 minutes
            "artist-credit": [{"artist": {"name": "Test Artist"}}],
            "release-list": [],
        }
        cm.musicbrainzngs.search_recordings = MagicMock(
            return_value={"recording-list": [recording]}
        )
        result = cm.MusicBrainzClient().enrich_track(
            title="Test Song",
            artists=["Test Artist"],
            duration_seconds=180,  # 3 minutes - way off
        )
        assert result is None, "Should reject tracks with >15% duration diff"
