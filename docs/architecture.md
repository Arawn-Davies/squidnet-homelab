# Architecture (overview)

```mermaid
flowchart LR
  internet((Internet)) -->|Cloudflare Tunnel| flareon[flareon<br/>nginx + CrowdSec bouncer]
  internet -->|UDP 51820| router[OpenWrt<br/>WireGuard, banIP]
  flareon --> jelly[Jellyfin primary]
  flareon -.backup upstream.-> spare[Jellyfin standby<br/>cold-spare node]
  flareon --> vault[Vaultwarden]
  flareon --> ntfy[ntfy]
  router --> lan[(LAN 10.0.0.0/16)]
  lan --> npm[Nginx Proxy Manager<br/>LAN-only + Authentik forward-auth]
  npm --> grafana[Grafana] & homepage[Homepage] & patch[squidpatch] & pve[Proxmox VE / PBS]
  authentik[Authentik SSO] --- npm
  authentik --- pve
  prom[Prometheus] --> grafana
  prom -->|scrapes| pve & router & switch[Core switch SNMP] & crowdsec[CrowdSec LAPI] & patch
  grafana -->|alerts| ntfy
  suricata[Suricata IDS<br/>tc mirror] -->|sev-1 alerts| ntfy
  crowdsec -->|bans| router
  stepca[step-ca SSH CA] --- authentik
  npm --> gitlab[GitLab CE<br/>backup of GitHub + runners] & romm[RomM game library<br/>LAN only, strict]
  authentik --- gitlab & romm
  gitlab -.nightly sync.-> github((GitHub))
  pihole[Pi-hole] -.CDN overrides.-> lancache[LANCache]
```

- **Nodes:** a Proxmox VE cluster of always-on nodes plus cold spares, sharing a ZFS storage; two PBS servers (hot + mirror on a cold spare, hourly pull sync while it's on). More detail in [diagrams.md](diagrams.md).
- **Public surface:** only the Cloudflare Tunnel (a handful of hostnames, all behind CrowdSec with custom brute-force scenarios) and the WireGuard port.
- **Everything else** is LAN/VPN only: local DNS on Pi-hole + the router, NPM access lists, Proxmox firewall IP sets (`lan`, `vpn`), and Authentik in front of admin UIs.
- **Git:** GitHub stays the primary; a self-hosted GitLab CE keeps a nightly, never-deleting copy of every repo and provides CI runners on homelab hardware ([gitlab/](../gitlab)).
- **Games:** a strictly LAN-only RomM library over the archive and a LANCache download cache steered by Pi-hole ([games/](../games)).

More: **[network.md](network.md)** (addressing, DNS, access tiers, firewall layers, VPN, IDS) and **[services.md](services.md)** (dependency map, request walk-throughs, per-service table, failure impact).

