# SQUIDNET homelab - dashboards & config as code

Everything needed to rebuild the monitoring, dashboards and security tooling of a Proxmox VE
homelab from scratch: Grafana dashboards and alerting, the Prometheus stack, the Homepage inventory,
Authentik SSO blueprints, the reverse proxies, CrowdSec, Suricata, ntfy, an SSH certificate authority,
a patch dashboard and a Jellyfin standby.

All self-hosted and FOSS. **No secrets are in this repo**: every credential is a `${PLACEHOLDER}`
listed in [`.env.example`](.env.example). Domains are `example.co.uk` (public) and
`lab.example.co.uk` (LAN-only) - replace them with your own.

## What's here

| Directory | What it is |
|---|---|
| [`grafana/`](grafana) | Dashboards (Proxmox cluster, core switch, OpenWrt router, CrowdSec x4, Patches), datasource provisioning, alert rules, ntfy contact point, notification policy |
| [`monitoring/proxmon/`](monitoring/proxmon) | Docker Compose stack: Prometheus, Grafana, pve-exporter, node-exporter, cAdvisor, SNMP exporter, with all scrape jobs inline |
| [`homepage/`](homepage) | [Homepage](https://gethomepage.dev) config + `inventory/gen.py`, which generates the service list from the Proxmox API, Docker and Pi-hole |
| [`squidpatch/`](squidpatch) | Agentless "outdated packages" dashboard for every node/CT/VM, with snapshot-then-upgrade buttons, Prometheus metrics and a Homepage widget endpoint |
| [`authentik/`](authentik) | Authentik blueprints: OIDC for Proxmox VE, PBS, Portainer, Grafana, Vaultwarden, step-ca, CrowdSec UI, GitLab, RomM; forward-auth for LAN pages |
| [`npm/`](npm) | Nginx Proxy Manager host list (domains → backends, access lists) and the Jellyfin failover upstream |
| [`flareon/`](flareon) | Public ingress: nginx behind a Cloudflare Tunnel, CrowdSec custom brute-force scenarios, LAPI firewall |
| [`router/`](router) | OpenWrt: WireGuard road-warrior VPN (routed, no NAT), peer/QR helper, DDNS, CrowdSec → banIP feed |
| [`suricata/`](suricata) | Suricata IDS in an LXC fed by a tc mirror of a node's NIC; ET Open rules; high-severity alerts → ntfy |
| [`ntfy/`](ntfy) | Self-hosted ntfy push notifications (deny-all, token publishers) |
| [`step-ca/`](step-ca) | SSH certificate authority: short-lived certs via Authentik OIDC, rollout script for `TrustedUserCAKeys` |
| [`gitlab/`](gitlab) | Self-hosted GitLab CE as a **backup of GitHub**: Authentik SSO, nightly GitHub → GitLab sync that never deletes, GitLab Runners (Docker executor) on two LXCs |
| [`games/`](games) | **LAN-only** game library (RomM + read-only file index) and LANCache download cache with Pi-hole DNS overrides |
| [`tools/`](tools) | `archive-inventory.py`: read-only inventory + content-duplicate finder for a large archive dataset |
| [`jellyfin-standby/`](jellyfin-standby) | Cold-standby Jellyfin on a spare node: incremental ZFS media sync, config sync, nginx `backup` upstream |
| [`docs/`](docs) | [Diagrams](docs/diagrams.md) (Mermaid), [architecture overview](docs/architecture.md) and the [rebuild guide](docs/REBUILD.md) |

## Grafana dashboards

Import any JSON under [`grafana/dashboards/`](grafana/dashboards) (Dashboards → New → Import), or provision
the whole folder. They expect a Prometheus datasource with uid `prometheus`
([`grafana/provisioning/datasources.yaml`](grafana/provisioning/datasources.yaml)).

- **Proxmox / proxmox-cluster-overview** - nodes, guests, storage, backups (prometheus-pve-exporter + node-exporter)
- **Network / core-switch** - ports, errors, PoE via the SNMP exporter
- **Network / OpenWrt** - router via node-exporter on OpenWrt
- **Security / CrowdSec** - four dashboards from [crowdsecurity/grafana-dashboards](https://github.com/crowdsecurity/grafana-dashboards) (MIT), fixed for Grafana 11
- **Security / Patches (squidpatch)** - outdated / security / critical updates per host

## Diagrams

Seven Mermaid diagrams (platform, public ingress, LAN + SSO, security layers, backups, monitoring/alerting,
VPN + SSH certificates) in [`docs/diagrams.md`](docs/diagrams.md).

## Rebuild

See [`docs/REBUILD.md`](docs/REBUILD.md).

## Licence

MIT for the original code and config here. The CrowdSec dashboards keep their upstream MIT licence.
