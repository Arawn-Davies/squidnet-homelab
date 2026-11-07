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
- Extras not in uklans are appended by the script (`LANCACHE_EXTRA_DOMAINS`, default `steampipe.akamaized.net`, Steam's Akamai depot CDN). Never add `akadns.net`: it is Akamai's shared traffic-steering domain, and CNAME targets don't need overriding because clients query the name they want.
- Every domain gets `address=/d/<cache IP>` **and** `local=/d/`: since dnsmasq 2.86 the IPv4 override alone no longer blocks AAAA, and clients that get the CDN's real IPv6 address skip the cache.
- The **router carries the same overrides** (`uci add_list dhcp.@dnsmasq[0].address=/d/<cache IP>` and `...server=/d/`, generated from Pi-hole's file). Clients use the router as their IPv6 DNS server, and its rebind protection drops the private answer it would get from Pi-hole, so without its own copy those clients bypass the cache. Check from a client: `nslookup lancache.steamcontent.com` must return the cache IP whichever server answers.
- LANCache's own upstream DNS is a public resolver, never the Pi-hole (otherwise it would resolve CDNs to itself).
- **What is it caching?** `lancache-report.sh` (read-only, on the cache host) lists every Steam depot with requests, MB, HIT/MISS and last request; `steam-depot-names.py` turns depot IDs into game names by asking Steam (anonymous login) which app owns each depot - run it in a throwaway `python:3.12-slim` container (usage in the file). SteamDB blocks scripts and `steamcmd` is 32-bit x86 only, which is why it uses the `steam` Python library.
- No web UI; only HTTP downloads are cached (logins/store pages are HTTPS and pass straight through).
