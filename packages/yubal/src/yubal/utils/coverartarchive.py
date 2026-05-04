"""Cover Art Archive (CAA) integration.

Fetches cover art from MusicBrainz's Cover Art Archive using release MBIDs
and release group MBIDs. Handles 307 redirects, JSON parsing, and graceful
degradation when no cover art is available.

Priority order for cover art selection:
1. CAA release MBID (front cover via 307 redirect)
2. CAA release-group MBID (JSON listing, pick best thumbnail)
3. Fallback to caller's alternative source (e.g., yt-dlp artwork_url)

Rate limiting: 1 request per second (same as MusicBrainz).
"""

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)

CAA_BASE = "https://coverartarchive.org"
_RATE_LIMIT_DELAY = 1.0


def _sleep_for_rate_limit() -> None:
    """Sleep briefly to respect CAA rate limits."""
    time.sleep(_RATE_LIMIT_DELAY)


def _import_requests() -> "import requests":
    """Lazy import of requests to avoid hard dependency."""
    import requests as _requests

    return _requests


def fetch_cover_from_release_mbid(
    release_mbid: str,
    timeout: float = 10.0,
) -> bytes | None:
    """Fetch front cover art from CAA using a release MBID.

    GET /release/{mbid}/front returns a 307 redirect to the actual image
    (usually archive.org). The requests library follows 307 automatically,
    so a 200 status code means the image was fetched successfully.

    Args:
        release_mbid: MusicBrainz release MBID.
        timeout: Request timeout in seconds.

    Returns:
        Image bytes (JPEG/PNG), or None if no cover art or request failed.
    """
    requests = _import_requests()

    url = f"{CAA_BASE}/release/{release_mbid}/front"
    logger.debug("Fetching CAA cover from release MBID: %s", release_mbid)

    try:
        _sleep_for_rate_limit()
        response = requests.get(url, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        logger.debug(
            "CAA release MBID request failed for %s: %s", release_mbid, exc
        )
        return None

    if response.status_code == 404:
        logger.debug("CAA returned 404 for release MBID: %s", release_mbid)
        return None

    if response.status_code == 400:
        logger.debug("CAA returned 400 (invalid MBID): %s", release_mbid)
        return None

    if response.status_code != 200:
        logger.debug(
            "CAA returned unexpected status %d for release MBID: %s",
            response.status_code,
            release_mbid,
        )
        return None

    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        logger.debug(
            "CAA release MBID response is not an image: %s", content_type
        )
        return None

    data = response.content
    logger.info(
        "Fetched CAA cover from release MBID %s (%d bytes, %s)",
        release_mbid,
        len(data),
        content_type,
    )
    return data


def fetch_cover_from_release_group_mbid(
    release_group_mbid: str,
    timeout: float = 10.0,
) -> bytes | None:
    """Fetch cover art from CAA using a release group MBID.

    GET /release-group/{mbid} returns JSON with an ``images`` array.
    Each image has ``thumbnails`` with various sizes. We pick the best
    available size (preferring 1200px, then large, then small).

    Args:
        release_group_mbid: MusicBrainz release group MBID.
        timeout: Request timeout in seconds.

    Returns:
        Image bytes (JPEG/PNG), or None if no cover art or request failed.
    """
    requests = _import_requests()

    url = f"{CAA_BASE}/release-group/{release_group_mbid}"
    logger.debug(
        "Fetching CAA cover from release-group MBID: %s", release_group_mbid
    )

    try:
        _sleep_for_rate_limit()
        response = requests.get(url, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        logger.debug(
            "CAA release-group MBID request failed for %s: %s",
            release_group_mbid,
            exc,
        )
        return None

    if response.status_code == 404:
        logger.debug(
            "CAA returned 404 for release-group MBID: %s", release_group_mbid
        )
        return None

    if response.status_code == 400:
        logger.debug(
            "CAA returned 400 (invalid MBID): %s", release_group_mbid
        )
        return None

    if response.status_code != 200:
        logger.debug(
            "CAA returned unexpected status %d for release-group MBID: %s",
            response.status_code,
            release_group_mbid,
        )
        return None

    try:
        data = response.json()
    except ValueError as exc:
        logger.debug(
            "CAA release-group MBID returned invalid JSON: %s", exc
        )
        return None

    images = data.get("images")
    if not images or not isinstance(images, list) or len(images) == 0:
        logger.debug(
            "CAA release-group MBID %s has no images", release_group_mbid
        )
        return None

    # Pick the best image: prefer first one with thumbnails
    selected_image = None
    for image in images:
        thumbnails = image.get("thumbnails")
        if thumbnails and isinstance(thumbnails, dict) and len(thumbnails) > 0:
            selected_image = image
            break

    if selected_image is None:
        # Fallback: pick first image that has a direct ``url``
        for image in images:
            if image.get("front") is True or image.get("type") == "Front":
                selected_image = image
                break

    if selected_image is None:
        selected_image = images[0]

    # Try to get the largest available thumbnail
    thumbnails = selected_image.get("thumbnails")
    image_url = None

    if thumbnails and isinstance(thumbnails, dict):
        # Prefer 1200, then large, then small, then any available
        for size_key in ("1200", "large", "small"):
            if size_key in thumbnails:
                image_url = thumbnails[size_key]
                logger.debug(
                    "CAA: picked %s thumbnail for release-group MBID %s",
                    size_key,
                    release_group_mbid,
                )
                break

    if image_url is None:
        # Fallback: use the direct image URL
        image_url = selected_image.get("image")

    if image_url is None:
        logger.debug(
            "CAA: no image URL found for release-group MBID %s",
            release_group_mbid,
        )
        return None

    # Fetch the actual image (may be a redirect)
    try:
        _sleep_for_rate_limit()
        response = requests.get(image_url, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        logger.debug(
            "CAA image fetch failed for %s: %s", image_url, exc
        )
        return None

    if response.status_code != 200:
        logger.debug(
            "CAA image returned status %d for %s",
            response.status_code,
            image_url,
        )
        return None

    content_type = response.headers.get("content-type", "")
    if not content_type.startswith("image/"):
        logger.debug(
            "CAA image response is not an image: %s", content_type
        )
        return None

    data = response.content
    logger.info(
        "Fetched CAA cover from release-group MBID %s (%d bytes, %s)",
        release_group_mbid,
        len(data),
        content_type,
    )
    return data


def fetch_cover_from_caa(
    release_mbid: str | None = None,
    release_group_mbid: str | None = None,
    timeout: float = 10.0,
) -> bytes | None:
    """Fetch cover art from CAA, trying multiple MBID sources.

    Tries release MBID first (more direct, single image), then falls back
    to release group MBID (JSON listing, pick best thumbnail).

    Args:
        release_mbid: MusicBrainz release MBID.
        release_group_mbid: MusicBrainz release group MBID.
        timeout: Request timeout in seconds.

    Returns:
        Image bytes (JPEG/PNG), or None if no cover art found.
    """
    # Try release MBID first (more specific, direct front cover)
    if release_mbid:
        logger.info(
            "Trying CAA cover from release MBID: %s", release_mbid
        )
        data = fetch_cover_from_release_mbid(release_mbid, timeout)
        if data is not None:
            logger.info(
                "CAA cover art resolved from release MBID %s", release_mbid
            )
            return data

    # Fallback to release group MBID
    if release_group_mbid:
        logger.info(
            "Trying CAA cover from release-group MBID: %s",
            release_group_mbid,
        )
        data = fetch_cover_from_release_group_mbid(
            release_group_mbid, timeout
        )
        if data is not None:
            logger.info(
                "CAA cover art resolved from release-group MBID %s",
                release_group_mbid,
            )
            return data

    logger.debug(
        "CAA: no cover art found for release_mbid=%s, release_group_mbid=%s",
        release_mbid,
        release_group_mbid,
    )
    return None


def get_cover_url_from_caa(
    release_mbid: str | None = None,
    release_group_mbid: str | None = None,
) -> str | None:
    """Get a cover art URL from CAA that the download pipeline can use.

    For release MBIDs, performs a HEAD request to verify the cover exists
    before returning the /front URL (307 redirect to image). This avoids
    returning URLs that would fail with 404/500 during the download phase.
    For release-group MBIDs, resolves the JSON to find the best thumbnail
    URL and returns it.

    The returned URL is suitable for use with urllib.request.urlopen,
    which is what the cover download pipeline uses.

    Args:
        release_mbid: MusicBrainz release MBID.
        release_group_mbid: MusicBrainz release group MBID.

    Returns:
        A cover art URL string, or None if no cover art found.
    """
    # Try release MBID first (direct front cover URL)
    if release_mbid:
        caa_url = f"{CAA_BASE}/release/{release_mbid}/front"
        # Use HEAD to verify the cover exists without downloading the body.
        # This avoids returning URLs that would fail with 404/500 later.
        requests = _import_requests()
        try:
            _sleep_for_rate_limit()
            response = requests.head(caa_url, timeout=10)
        except requests.exceptions.RequestException as exc:
            logger.debug(
                "CAA HEAD request failed for release MBID %s: %s",
                release_mbid,
                exc,
            )
            return None

        if response.status_code == 200:
            logger.debug(
                "CAA: returning cover URL from release MBID %s: %s",
                release_mbid,
                caa_url,
            )
            return caa_url
        logger.debug(
            "CAA: release MBID %s returned %d, no cover art",
            release_mbid,
            response.status_code,
        )

    # Fallback to release-group MBID (resolve thumbnail URL)
    if release_group_mbid:
        try:
            requests = _import_requests()
            url = f"{CAA_BASE}/release-group/{release_group_mbid}"
            _sleep_for_rate_limit()
            response = requests.get(url, timeout=10)

            if response.status_code != 200:
                logger.debug(
                    "CAA release-group MBID returned status %d: %s",
                    response.status_code,
                    release_group_mbid,
                )
                return None

            data = response.json()
            images = data.get("images")
            if not images or not isinstance(images, list) or len(images) == 0:
                logger.debug(
                    "CAA release-group MBID %s has no images",
                    release_group_mbid,
                )
                return None

            # Pick the best image
            selected_image = None
            for image in images:
                thumbnails = image.get("thumbnails")
                if (
                    thumbnails
                    and isinstance(thumbnails, dict)
                    and len(thumbnails) > 0
                ):
                    selected_image = image
                    break

            if selected_image is None:
                for image in images:
                    if (
                        image.get("front") is True
                        or image.get("type") == "Front"
                    ):
                        selected_image = image
                        break

            if selected_image is None:
                selected_image = images[0]

            # Get the largest available thumbnail
            thumbnails = selected_image.get("thumbnails")
            image_url = None
            if thumbnails and isinstance(thumbnails, dict):
                for size_key in ("1200", "large", "small"):
                    if size_key in thumbnails:
                        image_url = thumbnails[size_key]
                        logger.debug(
                            "CAA: picked %s thumbnail for release-group MBID %s",
                            size_key,
                            release_group_mbid,
                        )
                        break

            if image_url is None:
                image_url = selected_image.get("image")

            if image_url:
                logger.debug(
                    "CAA: returning cover URL from release-group MBID %s: %s",
                    release_group_mbid,
                    image_url,
                )
                return image_url

        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "CAA release-group URL resolution failed for %s: %s",
                release_group_mbid,
                exc,
            )

    return None
