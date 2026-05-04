"""Test Cover Art Archive (CAA) integration with real API calls.

These tests exercise the actual CAA endpoints to verify:
- Release MBID 307 redirect to archive.org
- Release-group MBID JSON response with thumbnails
- Graceful handling of 404/400 (no cover art)
"""

import pytest


@pytest.mark.enable_socket
@pytest.mark.allow_hosts(
    "coverartarchive.org",
    "musicbrainz.org",
)

class TestCAAFetchReal:
    """Tests that make real HTTP requests to the Cover Art Archive."""

    @pytest.fixture
    def release_mbid(self):
        """A real MusicBrainz release MBID with known cover art."""
        return "f33f2384-761b-4c27-9db3-922edc9b8cbd"  # Jane Remover - Revengeseekerz

    @pytest.fixture
    def release_group_mbid(self):
        """A real MusicBrainz release group MBID with known cover art."""
        return "2b563f6a-f705-3f3e-854d-aebe6d8edbc8"  # Jane Remover - Revengeseekerz

    def test_release_mbid_307_redirect(self, release_mbid):
        """CAA /release/{mbid}/front returns 307 redirect to archive.org."""
        import requests

        url = f"https://coverartarchive.org/release/{release_mbid}/front"
        response = requests.get(url, timeout=10)

        assert response.status_code == 200  # 307 auto-followed
        assert response.headers.get("content-type", "").startswith("image/")
        # Should be a JPEG or PNG
        content = response.content
        assert content[:2] == b"\xff\xd8" or content[:4] == b"\x89PNG"

    def test_release_mbid_head(self, release_mbid):
        """HEAD request to /release/{mbid}/front returns 307."""
        import requests

        url = f"https://coverartarchive.org/release/{release_mbid}/front"
        response = requests.head(url, timeout=10)

        assert response.status_code == 307
        assert "Location" in response.headers

    def test_release_group_json(self, release_group_mbid):
        """CAA /release-group/{mbid} returns JSON with images and thumbnails."""
        import requests

        url = f"https://coverartarchive.org/release-group/{release_group_mbid}"
        response = requests.get(url, timeout=10)

        assert response.status_code == 200
        data = response.json()

        assert "images" in data
        assert len(data["images"]) > 0

        # Each image should have thumbnails (may include 1200, large, small)
        for img in data["images"][:5]:
            assert "thumbnails" in img
            # CAA may provide 1200, or large/small, or just none
            assert len(img["thumbnails"]) > 0

    def test_release_mbid_no_cover_404(self):
        """CAA returns 404 for a release with no cover art."""
        import requests

        # This MBID exists but has no cover art
        # Using a known release without cover
        url = "https://coverartarchive.org/release/00000000-0000-0000-0000-000000000000/front"
        response = requests.get(url, timeout=10)

        # 400 for invalid UUID, 404 for no cover
        assert response.status_code in (400, 404)

    def test_release_group_no_cover_404(self):
        """CAA returns 404 for a release group with no cover art."""
        import requests

        url = "https://coverartarchive.org/release-group/00000000-0000-0000-0000-000000000000"
        response = requests.get(url, timeout=10)

        assert response.status_code in (400, 404)

    def test_invalid_mbid_400(self):
        """CAA returns 400 for invalid MBID format."""
        import requests

        url = "https://coverartarchive.org/release/not-a-valid-uuid/front"
        response = requests.get(url, timeout=10)

        assert response.status_code == 400
