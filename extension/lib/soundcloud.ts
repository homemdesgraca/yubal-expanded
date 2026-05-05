const SUPPORTED_HOSTS = new Set([
  "soundcloud.com",
  "www.soundcloud.com",
  "snd.sc",
]);

const TRACK_PATTERN =
  /^(?:https?:\/\/)?(?:www\.)?soundcloud\.com\/([a-zA-Z0-9_-]+)\/([a-zA-Z0-9_-]+)/;
const SET_PATTERN =
  /^(?:https?:\/\/)?(?:www\.)?soundcloud\.com\/([a-zA-Z0-9_-]+)\/sets\/([a-zA-Z0-9_-]+)/;
const SHORT_PATTERN = /^(?:https?:\/\/)?snd\.sc\/([a-zA-Z0-9_-]+)/;

export function isSoundCloudUrl(url: string): boolean {
  try {
    return SUPPORTED_HOSTS.has(new URL(url).hostname);
  } catch {
    return false;
  }
}

/** Returns true if the URL points to a SoundCloud page with extractable media. */
export function isSoundCloudMediaUrl(url: string): boolean {
  try {
    const u = new URL(url);
    if (!SUPPORTED_HOSTS.has(u.hostname)) return false;

    // snd.sc short URLs always resolve to a track
    if (u.hostname === "snd.sc") return true;

    // Set: /artist/sets/set-name (3 segments)
    const segments = u.pathname.replace(/\/+$/, "").split("/").filter(Boolean);
    if (segments.length === 3 && segments[1] === "sets") return true;
    // Track: /artist/track-name (2 segments)
    if (segments.length === 2) return true;

    return false;
  } catch {
    return false;
  }
}
