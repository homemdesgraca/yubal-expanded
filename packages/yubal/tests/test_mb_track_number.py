"""Test that MusicBrainz track position is extracted from release media."""

from unittest.mock import patch

from yubal.config import MusicBrainzConfig


def test_track_number_extracted_from_release_media():
    """Track number should be extracted from release media track number.

    MusicBrainz recordings include a release-list with media and track arrays.
    Each track has a 'number' field indicating its position within the release.
    This test verifies that the MusicBrainzClient.enrich_track() method
    extracts this track_number from the response.
    """
    from yubal.client import MusicBrainzClient

    client = MusicBrainzClient(MusicBrainzConfig())

    mock_response = {
        "recording-list": [
            {
                "id": "0c00e4b0-4e6b-3f8e-8b1a-1f1e1e1e1e1e",
                "title": "Psychoboost",
                "length": "218000",
                "artist-credit": [
                    {"artist": {"name": "Jane Remover"}, "name": "Jane Remover"},
                    {"artist": {"name": "Danny Brown"}, "name": "Danny Brown"},
                ],
                "release-list": [
                    {
                        "id": "release-mbid-123",
                        "title": "Revengeseekerz",
                        "date": "2025-03-31",
                        "media": [
                            {
                                "track": [
                                    {
                                        "id": "track-1",
                                        "number": "1",
                                        "title": "Track One",
                                        "position": "1",
                                    },
                                    {
                                        "id": "track-2",
                                        "number": "2",
                                        "title": "Track Two",
                                        "position": "2",
                                    },
                                    {
                                        "id": "0c00e4b0-4e6b-3f8e-8b1a-1f1e1e1e1e1e",
                                        "number": "3",
                                        "title": "Psychoboost",
                                        "position": "3",
                                    },
                                ],
                                "position": "1",
                            }
                        ],
                    }
                ],
            }
        ]
    }

    with patch(
        "yubal.client.musicbrainzngs.search_recordings", return_value=mock_response
    ):
        enrichment = client.enrich_track(
            title="Psychoboost",
            artists=["Jane Remover", "Danny Brown"],
            duration_seconds=218,
        )

    assert enrichment is not None
    assert enrichment["mb_title"] == "Psychoboost"
    assert enrichment["year"] == "2025"
    assert enrichment["track_number"] == 3
    assert enrichment["total_tracks"] == 3


def test_track_number_not_found_in_media():
    """If the matched recording is not found in the media list, track_number should be None."""
    from yubal.client import MusicBrainzClient

    client = MusicBrainzClient(MusicBrainzConfig())

    mock_response = {
        "recording-list": [
            {
                "id": "some-id",
                "title": "Some Track",
                "length": "180000",
                "artist-credit": [
                    {"artist": {"name": "Artist"}, "name": "Artist"},
                ],
                "release-list": [
                    {
                        "id": "release-id",
                        "title": "Album",
                        "date": "2024-01-01",
                        "media": [
                            {
                                "track": [
                                    {
                                        "id": "different-track-id",
                                        "number": "5",
                                        "title": "Some Track (Remix)",
                                        "position": "5",
                                    }
                                ],
                                "position": "1",
                            }
                        ],
                    }
                ],
            }
        ]
    }

    with patch(
        "yubal.client.musicbrainzngs.search_recordings", return_value=mock_response
    ):
        enrichment = client.enrich_track(
            title="Some Track",
            artists=["Artist"],
            duration_seconds=180,
        )

    assert enrichment is not None
    # track_number should be None since the recording ID doesn't match any track
    assert enrichment["track_number"] is None


def test_track_number_from_search_format():
    """Track number should be extracted from search results (medium-list/track-list)."""
    from yubal.client import MusicBrainzClient

    client = MusicBrainzClient(MusicBrainzConfig())

    mock_response = {
        "recording-list": [
            {
                "id": "0ba469ff-a111-4cfa-9db0-fb23667d9c42",
                "title": "Psychoboost",
                "length": "244890",
                "artist-credit": [
                    {"artist": {"name": "Jane Remover"}, "name": "Jane Remover"},
                ],
                "release-list": [
                    {
                        "id": "release-mbid",
                        "title": "Revengeseekerz",
                        "date": "2025-04-04",
                        "medium-list": [
                            {
                                "position": "1",
                                "format": "Digital Media",
                                "track-list": [
                                    {
                                        "id": "track-1",
                                        "number": "1",
                                        "title": "Track One",
                                        "length": "200000",
                                    },
                                    {
                                        "id": "track-2",
                                        "number": "2",
                                        "title": "Psychoboost",
                                        "length": "244000",
                                    },
                                    {
                                        "id": "track-3",
                                        "number": "3",
                                        "title": "Track Three",
                                        "length": "180000",
                                    },
                                ],
                                "track-count": 3,
                            }
                        ],
                    }
                ],
            }
        ]
    }

    with patch(
        "yubal.client.musicbrainzngs.search_recordings", return_value=mock_response
    ):
        enrichment = client.enrich_track(
            title="Psychoboost",
            artists=["Jane Remover"],
            duration_seconds=244,
        )

    assert enrichment is not None
    assert enrichment["track_number"] == 2
    # total_tracks reflects the full track list in the mock (3 tracks)
    assert enrichment["total_tracks"] == 3


def test_prefers_digital_media_over_vinyl():
    """Should prefer Digital Media format over Vinyl when both are present."""
    from yubal.client import MusicBrainzClient

    client = MusicBrainzClient(MusicBrainzConfig())

    mock_response = {
        "recording-list": [
            {
                "id": "test-id",
                "title": "Song",
                "length": "200000",
                "artist-credit": [
                    {"artist": {"name": "Artist"}, "name": "Artist"},
                ],
                "release-list": [
                    {
                        "id": "release-id",
                        "title": "Album",
                        "date": "2024-01-01",
                        "medium-list": [
                            # Vinyl first (would give "A2" which fails int parse -> None)
                            {
                                "position": "1",
                                "format": "12\" Vinyl",
                                "track-list": [
                                    {
                                        "id": "v1",
                                        "number": "A1",
                                        "title": "Other",
                                    },
                                    {
                                        "id": "v2",
                                        "number": "A2",
                                        "title": "Song",
                                    },
                                ],
                            },
                            # Digital second (would give 2)
                            {
                                "position": "1",
                                "format": "Digital Media",
                                "track-list": [
                                    {
                                        "id": "d1",
                                        "number": "1",
                                        "title": "Other",
                                    },
                                    {
                                        "id": "d2",
                                        "number": "2",
                                        "title": "Song",
                                    },
                                ],
                            },
                        ],
                    }
                ],
            }
        ]
    }

    with patch(
        "yubal.client.musicbrainzngs.search_recordings", return_value=mock_response
    ):
        enrichment = client.enrich_track(
            title="Song",
            artists=["Artist"],
            duration_seconds=200,
        )

    assert enrichment is not None
    # Should get track number 2 from Digital Media, not None from vinyl A2
    assert enrichment["track_number"] == 2


def test_track_number_vinyl_side_numbering():
    """Vinyl side numbering like 'A2' should be handled gracefully."""
    from yubal.client import MusicBrainzClient

    client = MusicBrainzClient(MusicBrainzConfig())

    mock_response = {
        "recording-list": [
            {
                "id": "vinyl-id",
                "title": "Song",
                "length": "200000",
                "artist-credit": [
                    {"artist": {"name": "Artist"}, "name": "Artist"},
                ],
                "release-list": [
                    {
                        "id": "release-id",
                        "title": "Album",
                        "date": "2024-01-01",
                        "medium-list": [
                            {
                                "position": "1",
                                "format": "12\" Vinyl",
                                "track-list": [
                                    {
                                        "id": "track-1",
                                        "number": "A1",
                                        "title": "Song",
                                    },
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }

    with patch(
        "yubal.client.musicbrainzngs.search_recordings", return_value=mock_response
    ):
        enrichment = client.enrich_track(
            title="Song",
            artists=["Artist"],
            duration_seconds=200,
        )

    assert enrichment is not None
    # Vinyl side numbering like 'A2' can't be parsed as int, should be None
    assert enrichment["track_number"] is None
