"""Test that musicbrainzngs works with the current MusicBrainz API.

This script verifies that the musicbrainzngs library can still communicate
with the MusicBrainz web service. It tests the core operations we'll need:
- User agent setup
- Recording search
- Recording lookup by ID
- Cover Art Archive access

Run with: uv run ./tests/test_musicbrainzngs.py
"""

import musicbrainzngs as mb
import time
import sys
import json


def setup():
    """Configure musicbrainzngs for yubal."""
    mb.set_useragent("yubal", "0.8.0-soundcloud-test", "https://github.com/guillevc/yubal")
    mb.set_rate_limit(1.0)  # 1 request per second (MB limit)
    print("[OK] User agent and rate limit configured")


def test_search_recordings():
    """Test searching for recordings by artist + title."""
    print("\n--- Test: search_recordings ---")

    # Search for a well-known track
    result = mb.search_recordings(query="Bohemian Rhapsody", artist="Queen", limit=5)

    recording_list = result.get("recording-list", [])
    print(f"Found {len(recording_list)} recordings for 'Bohemian Rhapsody' by Queen")

    if recording_list:
        first = recording_list[0]
        print(f"  Title: {first.get('title', 'N/A')}")
        print(f"  Length: {first.get('length', 'N/A')}")
        print(f"  ID: {first.get('id', 'N/A')}")

        # artist-credit is a list
        artist_credit = first.get("artist-credit", [])
        if isinstance(artist_credit, list) and artist_credit:
            artist_entry = artist_credit[0]
            artist = artist_entry.get("artist", {})
            print(f"  Artist: {artist.get('name', 'N/A')}")

        # Check for release info
        releases = first.get("release-list", [])
        print(f"  Releases: {len(releases)}")
        if releases:
            rel = releases[0]
            print(f"    Release title: {rel.get('title', 'N/A')}")
            print(f"    Release date: {rel.get('date', 'N/A')}")
            print(f"    Release ID: {rel.get('id', 'N/A')}")
            print(f"    Release group ID: {rel.get('release-group', {}).get('id', 'N/A')}")
    else:
        print("  ERROR: No recordings found")
        return False

    time.sleep(1.1)
    return True


def test_get_recording_by_id():
    """Test looking up a recording by MBID.

    Valid includes for recordings:
    - artists, releases, discids, media, artist-credits, isrcs
    - work-level-rels, annotation, aliases, tags, user-tags, ratings, user-ratings
    - area-rels, artist-rels, label-rels, place-rels, event-rels
    - recording-rels, release-rels, release-group-rels, series-rels, url-rels, work-rels, instrument-rels
    """
    print("\n--- Test: get_recording_by_id ---")

    # First search to get a valid ID, then lookup
    result = mb.search_recordings(query="Bohemian Rhapsody", artist="Queen", limit=1)
    recording_list = result.get("recording-list", [])
    if not recording_list:
        print("  ERROR: No recordings found for ID lookup")
        return False

    recording_id = recording_list[0]["id"]
    print(f"  Using recording ID: {recording_id}")

    # Valid includes for recordings (no "release-groups" directly)
    includes = ["releases", "artist-credits", "release-group-rels"]

    result = mb.get_recording_by_id(recording_id, includes=includes)
    recording = result.get("recording", {})

    print(f"  Title: {recording.get('title', 'N/A')}")
    print(f"  Length: {recording.get('length', 'N/A')}")
    print(f"  ID: {recording.get('id', 'N/A')}")

    # Check artist credits (list of dicts)
    artist_credits = recording.get("artist-credit", [])
    print(f"  Artist credits count: {len(artist_credits)}")
    if artist_credits:
        first_credit = artist_credits[0]
        artist = first_credit.get("artist", {})
        print(f"    Artist name: {artist.get('name', 'N/A')}")
        print(f"    Artist ID: {artist.get('id', 'N/A')}")

    # Check releases
    releases = recording.get("release-list", [])
    print(f"  Releases: {len(releases)}")
    if releases:
        rel = releases[0]
        print(f"    Release title: {rel.get('title', 'N/A')}")
        print(f"    Release date: {rel.get('date', 'N/A')}")
        print(f"    Release ID: {rel.get('id', 'N/A')}")

        # Release group via release-group-rels
        rg_rels = rel.get("release-group-rels", [])
        if rg_rels:
            rg = rg_rels[0]
            print(f"    Release group: {rg.get('title', 'N/A')}")
            print(f"    RG ID: {rg.get('id', 'N/A')}")

    time.sleep(1.1)
    return True


def test_search_release_groups():
    """Test searching for release groups (albums)."""
    print("\n--- Test: search_release_groups ---")

    result = mb.search_release_groups(query="London Calling", artist="The Clash", limit=5)

    rg_list = result.get("release-group-list", [])
    print(f"Found {len(rg_list)} release groups for 'London Calling' by The Clash")

    if rg_list:
        first = rg_list[0]
        print(f"  Title: {first.get('title', 'N/A')}")
        print(f"  Type: {first.get('type', 'N/A')}")
        print(f"  ID: {first.get('id', 'N/A')}")

        # Check releases in this release group
        releases = first.get("release-list", [])
        print(f"  Releases: {len(releases)}")
        if releases:
            rel = releases[0]
            print(f"    Release title: {rel.get('title', 'N/A')}")
            print(f"    Release date: {rel.get('date', 'N/A')}")
            print(f"    Release ID: {rel.get('id', 'N/A')}")
    else:
        print("  ERROR: No release groups found")
        return False

    time.sleep(1.1)
    return True


def test_cover_art_archive():
    """Test Cover Art Archive access."""
    print("\n--- Test: Cover Art Archive ---")

    # Known release with cover art
    release_id = "661929d9-cfd1-408f-b40e-6b2b3d5ff374"
    print(f"  Using release ID: {release_id}")

    # List available cover art
    art_list = mb.get_image_list(release_id)
    images = art_list.get("images", [])
    print(f"  Found {len(images)} cover art images")

    if images:
        first_image = images[0]
        print(f"  Types: {first_image.get('types', [])}")
        print(f"  Front: {first_image.get('front', False)}")
        print(f"  Approved: {first_image.get('approved', False)}")
        thumbnails = first_image.get("thumbnails", {})
        print(f"  Thumbnails: {list(thumbnails.keys())}")
        if "1200" in thumbnails:
            print(f"  1200px URL available: YES")
        else:
            print(f"  1200px URL available: NO")
    else:
        print("  No cover art found for this release")
        return False

    time.sleep(1.1)
    return True

    # MusicBrainz CAA uses musicbrainzngs.get_image_list() and get_image_front()
    # Let's check what's available
    print(f"  Available CAA functions:")
    caa_funcs = [f for f in dir(mb) if "image" in f.lower() or "cover" in f.lower()]
    for func in caa_funcs:
        print(f"    - {func}")

    # Try get_image_list (the actual function name in v0.7.1)
    try:
        art_list = mb.get_image_list(release_id)
        images = art_list.get("images", [])
        print(f"  Found {len(images)} cover art images")

        if images:
            first_image = images[0]
            print(f"  Types: {first_image.get('types', [])}")
            print(f"  Front: {first_image.get('front', False)}")
            print(f"  Approved: {first_image.get('approved', False)}")
            thumbnails = first_image.get("thumbnails", {})
            print(f"  Thumbnails: {list(thumbnails.keys())}")
            if "1200" in thumbnails:
                print(f"  1200px URL available: YES")
            else:
                print(f"  1200px URL available: NO")
        else:
            print("  No cover art found for this release")

    except mb.ResponseError as e:
        print(f"  ERROR: CAA request failed: {e}")
        return False

    time.sleep(1.1)
    return True


def test_cover_art_download():
    """Test downloading cover art (just the metadata, not the actual image)."""
    print("\n--- Test: Cover Art Download (metadata only) ---")

    # Same known release
    release_id = "661929d9-cfd1-408f-b40e-6b2b3d5ff374"

    try:
        art_list = mb.get_image_list(release_id)
        images = art_list.get("images", [])

        front_images = [img for img in images if img.get("front")]
        if front_images:
            img = front_images[0]
            print(f"  Front cover found: {img.get('id', 'N/A')}")
            thumbnails = img.get("thumbnails", {})
            for size in ["250", "500", "1200"]:
                if size in thumbnails:
                    print(f"  {size}px thumbnail: available")
                else:
                    print(f"  {size}px thumbnail: NOT available")
        else:
            print("  No front cover found")

    except mb.ResponseError as e:
        print(f"  ERROR: {e}")
        return False

    time.sleep(1.1)
    return True


def test_release_search_for_track_info():
    """Test searching releases to get track numbers and disc info."""
    print("\n--- Test: Release search with media info ---")

    # Use the same known release
    release_id = "661929d9-cfd1-408f-b40e-6b2b3d5ff374"
    includes = ["media", "recordings", "artist-credits"]
    full_release = mb.get_release_by_id(release_id, includes=includes)
    release_data = full_release.get("release", {})

    print(f"  Release: {release_data.get('title', 'N/A')}")
    print(f"  Release ID: {release_data.get('id', 'N/A')}")
    print(f"  Date: {release_data.get('date', 'N/A')}")

    media_list = release_data.get("media", [])
    print(f"  Media: {len(media_list)}")
    for i, medium in enumerate(media_list):
        print(f"    Disc {i+1}: {medium.get('track-count', 0)} tracks")
        track_list = medium.get("track-list", [])
        for track in track_list:
            recording = track.get("recording", {})
            position = track.get("number", "N/A")
            print(f"      Track {position}: {recording.get('title', 'N/A')}")

    time.sleep(1.1)
    return True


def test_real_world_search():
    """Test a realistic SoundCloud-like search scenario."""
    print("\n--- Test: Real-world search (SoundCloud-like query) ---")

    # Search for a track that might have a stage name or handle on SoundCloud
    # but a canonical name on MusicBrainz
    result = mb.search_recordings(query="Blinding Lights", artist="The Weeknd", limit=5)

    recording_list = result.get("recording-list", [])
    print(f"Found {len(recording_list)} recordings for 'Blinding Lights' by The Weeknd")

    if recording_list:
        first = recording_list[0]
        print(f"  Title: {first.get('title', 'N/A')}")
        artist_credit = first.get("artist-credit", [])
        if isinstance(artist_credit, list) and artist_credit:
            artist = artist_credit[0].get("artist", {})
            print(f"  Artist: {artist.get('name', 'N/A')}")
        print(f"  Length: {first.get('length', 'N/A')}")
        print(f"  ID: {first.get('id', 'N/A')}")
    else:
        print("  ERROR: No recordings found")
        return False

    time.sleep(1.1)
    return True


def main():
    print("=" * 60)
    print("musicbrainzngs Compatibility Test")
    print("=" * 60)

    setup()

    tests = [
        ("Search recordings", test_search_recordings),
        ("Get recording by ID", test_get_recording_by_id),
        ("Search release groups", test_search_release_groups),
        ("Cover Art Archive", test_cover_art_archive),
        ("Cover Art Download", test_cover_art_download),
        ("Release search with media info", test_release_search_for_track_info),
        ("Real-world search", test_real_world_search),
    ]

    results = {}
    for name, test_func in tests:
        try:
            success = test_func()
            results[name] = "PASS" if success else "FAIL"
        except Exception as e:
            print(f"  EXCEPTION: {e}")
            results[name] = "ERROR"

    print("\n" + "=" * 60)
    print("Results:")
    print("=" * 60)
    all_passed = True
    for name, result in results.items():
        status = "PASS" if result == "PASS" else "FAIL" if result == "FAIL" else "ERROR"
        symbol = "PASS" if result == "PASS" else "FAIL"
        print(f"  {symbol} {name}: {status}")
        if result != "PASS":
            all_passed = False

    print()
    if all_passed:
        print("All tests passed! musicbrainzngs is compatible with the current MusicBrainz API.")
        return 0
    else:
        print("Some tests failed. See output above for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
