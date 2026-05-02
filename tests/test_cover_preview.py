"""Preview cover art for Jane Remover - Revengeseekerz.

Uses ytmusicapi (already a yubal dependency) to search and fetch cover.

Run with: .venv/bin/python ./tests/test_cover_preview.py
"""

import ytmusicapi
import urllib.request
import re
import sys


def search_ytmusic(query: str):
    """Search YouTube Music and return first album result."""
    ytm = ytmusicapi.YTMusic()
    results = ytm.search(query, filter="albums", limit=5)
    for r in results:
        if r.get("resultType") == "album":
            return r
    return None


def fetch_cover(url: str, timeout: float = 30.0) -> bytes | None:
    """Fetch cover image bytes from URL."""
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "yubal/0.8.0"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except Exception as e:
        print(f"Fetch error: {e}")
    return None


def upscale_url(url: str, size: int = 1200) -> str:
    """Upscale YouTube thumbnail URL to desired size."""
    return re.sub(r"=w\d+-h\d+", f"=w{size}-h{size}", url)


def main():
    query = "Jane Remover Revengeseekerz album"
    print(f"Searching YouTube Music for: {query}")
    print()

    info = search_ytmusic(query)
    if not info:
        print("ERROR: Could not find track on YouTube Music")
        return 1

    print(f"Title: {info.get('title', 'N/A')}")
    print(f"Video ID: {info.get('videoId', 'N/A')}")
    print(f"Artist: {info.get('artists', [{}])[0].get('name', 'N/A') if info.get('artists') else 'N/A'}")

    # Get thumbnails
    thumbnails = info.get("thumbnails", [])
    if not thumbnails:
        print("No thumbnails found")
        return 1

    # Find the largest thumbnail
    largest = max(thumbnails, key=lambda t: t.get("width", 0))
    original_url = largest.get("url", "")
    original_size = largest.get("width", 0)
    print(f"Original thumbnail: {original_size}x{largest.get('height', 0)}")
    print(f"Original URL: {original_url}")
    print()

    # Upscale to 1200px
    upscaled_url = upscale_url(original_url, 1200)
    print(f"Upscaled URL (1200px): {upscaled_url}")
    print()

    # Fetch the upscaled image
    print("Fetching 1200px cover...")
    data = fetch_cover(upscaled_url)
    if data:
        print(f"  Downloaded: {len(data):,} bytes ({len(data)/1024:.1f} KB)")
        print(f"  First bytes: {data[:4].hex()}")

        # Save to file for viewing
        output_path = "./tests/jane_remover_revengeseekerz_1200.jpg"
        with open(output_path, "wb") as f:
            f.write(data)
        print(f"\n  Saved to: {output_path}")
        print("  Open it in your image viewer to check quality.")
    else:
        print("  Failed to fetch 1200px cover")

        # Try original size as fallback
        print("\nTrying original size...")
        data = fetch_cover(original_url)
        if data:
            print(f"  Downloaded: {len(data):,} bytes ({len(data)/1024:.1f} KB)")
            output_path = "./tests/jane_remover_revengeseekerz_original.jpg"
            with open(output_path, "wb") as f:
                f.write(data)
            print(f"  Saved to: {output_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
