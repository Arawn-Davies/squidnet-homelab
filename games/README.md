# Games: private game library (RomM) + download cache (LANCache)

**LAN only by design.** Neither is reachable from the internet: no tunnel entry, no public DNS, a strict LAN-only access list on the reverse proxy, and container firewalls that only accept the proxy.

## RomM - `gaming.lab.example.co.uk`
A self-hosted catalogue of every system's games, BIOS/firmware, OS images and PC installers (think of a private Vimm's-Lair-style browser).
- **Layout**: one root on the archive dataset, `Gaming/gamelib/` → `roms/<platform>/`, `bios/<platform>/` (indexed by RomM), plus `PC/<Game>/{DOS,Windows,GOG}/`, `OS/<family>/`, `Frontends/` (served by a read-only nginx index at `/files/`). Single ZFS dataset, so reorganising is instant renames.
- **Container**: unprivileged LXC with Docker - `rommapp/romm` + MariaDB + `nginx` (autoindex, GET/HEAD only). The library is bind-mounted **read-write** with a uid/gid 1000 passthrough idmap and RomM running as `1000:1000`, so anything RomM creates belongs to the same user as the SMB share (RomM's setup wizard insists on creating platform folders).
- **Login**: Authentik OIDC (`authentik/blueprints/squidlab-romm.yaml`, admin user only).
- **Metadata without accounts**: LaunchBox + Hasheous enabled by default; IGDB / ScreenScraper / SteamGridDB / RetroAchievements keys can be added later from a hidden prompt.
- **New files appear automatically**: filesystem watcher (5 min debounce) + nightly scheduled rescan.

## LANCache - transparent download cache
`lancachenet/monolithic` in an unprivileged LXC; cache on its own ZFS dataset (quota 1 TB, `recordsize=1M`, `compression=off`, cache 950 GB). Re-downloadable data, so it can live on the bulk pool.
- **How clients use it**: purely DNS. `lancache-dns.sh` builds a dnsmasq file for Pi-hole from [uklans/cache-domains](https://github.com/uklans/cache-domains) (Steam, Epic, Blizzard, Riot, EA, Ubisoft, Xbox, Nintendo, PlayStation; Windows Update deliberately left out). Pi-hole v6 needs `misc.etc_dnsmasq_d=true` - **check `/etc/dnsmasq.d` first**: enabling it here woke up a forgotten PXE file that started a TFTP server.
- LANCache's own upstream DNS is a public resolver, never the Pi-hole (otherwise it would resolve CDNs to itself).
- No web UI; only HTTP downloads are cached (logins/store pages are HTTPS and pass straight through).
