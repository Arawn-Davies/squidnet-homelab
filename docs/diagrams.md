# Diagrams

Mermaid diagrams of the setup (GitHub renders them inline). Deliberately generic: roles, not hardware.
Domains are placeholders - `example.co.uk` is public, `lab.example.co.uk` is LAN/VPN-only.

1. [Platform](#1-platform)
2. [Public ingress](#2-public-ingress)
3. [LAN access, DNS and SSO](#3-lan-access-dns-and-sso)
4. [Security layers](#4-security-layers)
5. [Backups and resilience](#5-backups-and-resilience)
6. [Monitoring, alerting and inventory](#6-monitoring-alerting-and-inventory)
7. [Remote access and SSH certificates](#7-remote-access-and-ssh-certificates)

## 1. Platform

```mermaid
flowchart TB
  isp["ISP router (upstream)"] --- router["Edge router (OpenWrt)<br/>DHCP · DNS forwarder · banIP · WireGuard"]
  router --- sw["Core switch"]
  subgraph CLUSTER["Proxmox VE cluster (shared ZFS storage, LXC first, VMs where needed)"]
    direction TB
    subgraph ON["Always-on nodes"]
      edge["Edge & identity<br/>tunnel + nginx + CrowdSec · reverse proxy · DNS · SSO · password manager"]
      mon["Monitoring<br/>Prometheus · Grafana · Homepage · NetAlertX · patch dashboard"]
      media["Media<br/>Jellyfin (hardware transcoding) · file shares"]
      sec["Security services<br/>IDS · push notifications · SSH CA"]
      bkp["Backup server (hot)"]
    end
    subgraph COLD["Cold-spare nodes (powered on when needed)"]
      standby["Jellyfin standby (software transcoding)"]
      bkp2["Backup server mirror"]
      misc["Remote desktop gateway · spare capacity"]
    end
  end
  sw --- ON & COLD
```

## 2. Public ingress

```mermaid
flowchart LR
  user((Internet user)) --> cf["Cloudflare edge"]
  cf -- "Cloudflare Tunnel (outbound only)" --> cfd["cloudflared"]
  cfd --> ngx["nginx<br/>real IP from CF-Connecting-IP<br/>no query strings in logs<br/>CrowdSec bouncer"]
  ngx -- media --> up{{"upstream with failover"}}
  up -- primary --> jf["Jellyfin"]
  up -. "backup (only when the spare is on)" .-> jfs["Jellyfin standby"]
  ngx -- vault --> vw["Vaultwarden<br/>admin page LAN-only"]
  ngx -- ntfy --> nt["ntfy<br/>deny-all, login required"]
  cs["CrowdSec engine (self-hosted, CAPI off)<br/>custom brute-force scenarios + hub collections"] -. reads nginx logs .- ngx
  cs -. decisions .-> ngx
  cs -. "bans every 2 min" .-> banip["Router banIP<br/>(inbound + outbound)"]
  user -- "single UDP port" --> wg["WireGuard on the router"]
```

## 3. LAN access, DNS and SSO

```mermaid
flowchart LR
  client((LAN / VPN client)) -- DNS --> dns["Pi-hole + router dnsmasq"]
  dns -. "*.lab.example.co.uk → reverse proxy" .-> client
  client -- HTTPS --> npm["Nginx Proxy Manager<br/>wildcard cert<br/>'LAN only' list = LAN + VPN"]
  npm --> pve["Proxmox VE nodes"]
  npm --> pbs["Backup server + mirror"]
  npm --> graf["Grafana"]
  npm --> port["Portainer"]
  npm --> bmc["BMC / KVM web console"]
  npm --> rdp["Remote desktop gateway"]
  npm --> jfl["Jellyfin (failover upstream)"]
  npm -- "forward auth" --> fa["Homepage · NetAlertX · Pi-hole · patch dashboard"]
  ca["SSH CA (direct, pinned root)"]
  ak["Authentik"]
  fa -. outpost .-> ak
  pve & pbs & graf & port -. OIDC .-> ak
  vwsso["Vaultwarden (optional SSO; master password still required)"] -. OIDC .-> ak
  ca -. OIDC .-> ak
  jfl -. "never SSO (friends use native logins)" .- ak
```

## 4. Security layers

```mermaid
flowchart TB
  wan((WAN)) --> nat["Double NAT: one UDP port forwarded (WireGuard), nothing else"]
  nat --> banip["Router banIP: public threat feeds (in) + DNS blocklist (out)<br/>+ CrowdSec ban decisions (in + out)"]
  banip --> vpn["WireGuard subnet<br/>routed, never NATed · DNS + ICMP to the router only<br/>private hosts rejected at the router"]
  tunnel((Cloudflare Tunnel)) --> crowd["nginx + CrowdSec"]
  crowd --> apps["Public apps: media · password manager · notifications"]
  vpn & apps --> pvefw["Proxmox firewall<br/>IP sets 'lan' and 'vpn' (never merged)<br/>management + file-share groups · per-guest rules"]
  pvefw --> dockerfw["DOCKER-USER rules (-i eth0) on Docker hosts"]
  pvefw --> ssh["SSH: short-lived certificates from the CA (SSO login)"]
  mirror["tc mirror of a node NIC + the tunnel container"] --> ids["Suricata IDS (ET Open, detect-only)<br/>alerts only, private hosts excluded"]
  ids -- "high severity" --> ntfy["ntfy push"]
  patch["Patch dashboard: outdated / security / critical updates per host"] -- "Grafana alert" --> ntfy
  smb["Samba: SMB2+ only, signing, no guests, LAN-only (SMB1 isolated in one container)"]
```

## 5. Backups and resilience

```mermaid
flowchart LR
  guests["All guests (root disks)"] -- "weekly, keep 4 weekly + 6 monthly" --> hot["Backup server (hot)"]
  cavm["SSH CA VM"] -- "daily, client-side ENCRYPTED" --> hot
  hot -- "hourly pull sync incl. deletions<br/>(whenever the spare is on)" --> mir["Backup server mirror (cold spare)"]
  live["Media dataset (ZFS)"] -- "incremental zfs send<br/>at spare boot + nightly" --> bk["Read-only media copy (cold spare)"]
  bk -- "writable ZFS clone" --> spare["Jellyfin standby<br/>users, logins, watch state copied"]
  live -. "additive copy" .-> old["Older offline copy"]
  upg["Patch dashboard upgrades"] -- "snapshot first (kept 7 days)" --> guests
```

## 6. Monitoring, alerting and inventory

```mermaid
flowchart LR
  prom["Prometheus"] --> n["node exporters (all nodes)"]
  prom --> pvex["Proxmox exporter (read-only token)"]
  prom --> snmp["Core switch via SNMPv3"]
  prom --> owrt["Router node exporter"]
  prom --> csm["CrowdSec metrics"]
  prom --> spm["Patch dashboard /metrics"]
  prom --> graf["Grafana: Proxmox · Network · Security"]
  graf -- "alert rules: critical updates, check failing,<br/>stale data, OS end-of-life" --> ntfy["ntfy: alerts topic"]
  ids["Suricata"] --> ntfy2["ntfy: IDS topic"]
  ntfy & ntfy2 --> phone(("Phone app"))
  gen["Homepage generator (timer)"] --> hp["Homepage: Home · Guests · Network"]
  gen -. "Proxmox API (read-only)" .-> pveapi["Proxmox"]
  gen -. "Docker socket proxies" .-> dk["Docker hosts"]
  gen -. "Pi-hole API" .-> phapi["DNS clients"]
  nax["NetAlertX ARP scan"] --> hp
  sp["Patch dashboard summary"] --> hp
```

## 7. Remote access and SSH certificates

```mermaid
sequenceDiagram
  autonumber
  participant D as Phone / laptop
  participant R as Router (WireGuard)
  participant L as LAN services
  participant C as step CLI
  participant A as Authentik
  participant S as step-ca
  participant H as Any server
  D->>R: WireGuard handshake (DDNS name, one UDP port)
  R->>L: routed with its own VPN address (not NAT), private hosts rejected
  Note over D,L: *.lab.example.co.uk works because the 'LAN only' list includes the VPN
  C->>A: browser login (OIDC, loopback callback)
  A-->>C: ID token (app bound to one user)
  C->>S: sign my SSH key (OIDC provisioner)
  S-->>C: user certificate: fixed principals, 24 h default, 7 days max, no renewal
  C->>H: ssh with the certificate
  H-->>C: accepted via TrustedUserCAKeys (no authorized_keys needed)
```
