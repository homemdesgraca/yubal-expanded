import { EmptyState } from "@/components/common/empty-state";
import { useLocalStorage } from "@/hooks/use-local-storage";
import { showErrorToast } from "@/lib/toast";
import { Button, Input, Spinner, Table, TableBody, TableCell, TableColumn, TableHeader, TableRow } from "@heroui/react";
import { InboxIcon, ListMusicIcon, PlusIcon, RefreshCwIcon, Search, UserIcon } from "lucide-react";
import { useCallback, useState } from "react";

const LB_LOCALSTORAGE_KEY = "yubal:listenbrainz:username";

export function ListenBrainzTab() {
  const [username, setUsername] = useLocalStorage<string>(LB_LOCALSTORAGE_KEY, "");
  const [playlists, setPlaylists] = useState<
    Array<{ mbid: string; name: string; track_count: number }>
  >([]);
  const [isSearching, setIsSearching] = useState(false);

  const handleSearch = useCallback(async () => {
    if (!username.trim()) return;
    setIsSearching(true);
    try {
      // TODO: Replace with real API call (Phase 2)
      // const data = await fetchListenBrainzPlaylists(username.trim());
      // setPlaylists(data.playlists);
      setPlaylists([]); // Stub returns empty
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to fetch playlists";
      showErrorToast("Search failed", message);
    } finally {
      setIsSearching(false);
    }
  }, [username]);

  const handleSubscribe = useCallback(
    async (_mbid: string) => {
      try {
        // TODO: Replace with real API call (Phase 2)
        // await subscribeToListenBrainzPlaylist(mbid);
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to subscribe";
        showErrorToast("Subscribe failed", message);
      }
    },
    [],
  );

  const handleDownload = useCallback(
    async (_mbid: string) => {
      try {
        // TODO: Replace with real API call (Phase 2)
        // await downloadListenBrainzPlaylist(mbid);
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to download";
        showErrorToast("Download failed", message);
      }
    },
    [],
  );

  const columns = [
    { name: "PLAYLIST", key: "name" },
    { name: "TRACKS", key: "track_count" },
    { name: "ACTIONS", key: "actions" },
  ];

  return (
    <>
      {/* Username + Search */}
      <section className="mb-6 flex gap-2">
        <div className="flex-1">
          <Input
            type="text"
            placeholder="ListenBrainz username"
            value={username}
            onValueChange={(v) => setUsername(v)}
            isDisabled={isSearching}
            radius="lg"
            startContent={<UserIcon className="text-foreground-400 h-4 w-4" />}
          />
        </div>
        <Button
          color="primary"
          radius="lg"
          variant={username.trim() ? "shadow" : "solid"}
          className="shadow-primary-100/50"
          onPress={handleSearch}
          isDisabled={!username.trim()}
          isLoading={isSearching}
          startContent={!isSearching && <Search className="h-4 w-4" />}
        >
          Search
        </Button>
      </section>

      {/* Playlist Table */}
      {isSearching ? (
        <div className="flex justify-center py-12">
          <Spinner label="Loading playlists..." color="primary" />
        </div>
      ) : (
        <Table
          aria-label="ListenBrainz playlists"
        >
          <TableHeader columns={columns}>
            {(column) => (
              <TableColumn
                key={column.key}
                align={column.key === "actions" ? "center" : "start"}
              >
                {column.name}
              </TableColumn>
            )}
          </TableHeader>
          <TableBody items={playlists} emptyContent={<EmptyState icon={InboxIcon} title="No playlists found" description="Enter a username above to browse their ListenBrainz playlists" />}>
            {(playlist) => (
              <TableRow key={playlist.mbid}>
                {(columnKey) => (
                  columnKey === "name" ? (
                    <TableCell>
                      <div className="flex items-center gap-4">
                        <div className="bg-content3 flex h-10 w-10 shrink-0 items-center justify-center rounded">
                          <ListMusicIcon className="text-foreground-400 h-5 w-5" />
                        </div>
                        <span className="font-mono text-sm">{playlist.name}</span>
                      </div>
                    </TableCell>
                  ) : columnKey === "track_count" ? (
                    <TableCell>
                      <span className="text-foreground-500 font-mono text-sm">
                        {playlist.track_count}
                      </span>
                    </TableCell>
                  ) : (
                    <TableCell>
                      <div className="flex items-center justify-center gap-1">
                        <Button
                          variant="light"
                          size="sm"
                          isIconOnly
                          className="text-foreground-500 hover:text-primary"
                          onPress={() => handleSubscribe(playlist.mbid)}
                        >
                          <PlusIcon className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="light"
                          size="sm"
                          isIconOnly
                          className="text-foreground-500 hover:text-danger"
                          onPress={() => handleDownload(playlist.mbid)}
                        >
                          <RefreshCwIcon className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  )
                )}
              </TableRow>
            )}
          </TableBody>
        </Table>
      )}
    </>
  );
}
