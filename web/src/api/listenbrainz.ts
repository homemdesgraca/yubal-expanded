// Stubbed — real implementation pending backend (Phase 2)

export interface ListenBrainzPlaylist {
  mbid: string;
  name: string;
  track_count: number;
  description?: string;
}

export interface ListenBrainzPlaylistListResponse {
  playlists: ListenBrainzPlaylist[];
  username: string;
}

// --- Stubbed — real implementation pending backend (Phase 2) ---

export async function fetchListenBrainzPlaylists(
  _username: string,
): Promise<ListenBrainzPlaylist[]> {
  throw new Error("Not implemented");
}

export async function subscribeToListenBrainzPlaylist(
  _mbid: string,
): Promise<{ success: true; id: string } | { success: false; error: string }> {
  throw new Error("Not implemented");
}

export async function downloadListenBrainzPlaylist(
  _mbid: string,
): Promise<{ success: true; job_id: string } | { success: false; error: string }> {
  throw new Error("Not implemented");
}
