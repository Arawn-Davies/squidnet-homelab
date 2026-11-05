#!/usr/bin/env python3
"""Homepage inventory generator for lab.example.co.uk (CT104).

Builds config/services.yaml and config/settings.yaml from:
  - inventory/static_services.json   hand-edited "Home" tab groups
  - inventory/settings_base.json     Homepage settings without the layout
  - inventory/links.json             IP -> URL map for guest cards
  - inventory/names.json             MAC -> friendly name for the Network tab
  - Proxmox API (read-only token)    guests, nodes, IPs           -> "Guests" tab
  - Docker socket proxies (read-only) containers on CT104/CT116  -> "Guests" tab
  - Pi-hole v6 API (app password)    every IPv4 seen on the LAN   -> "Network" tab
Outputs are JSON, which is valid YAML. Stdlib only. Never prints secrets.
"""
import json, os, ssl, sys, time, datetime, urllib.request, urllib.error

BASE = "/root/stacks/homelab"
INV = f"{BASE}/inventory"
CFG = f"{BASE}/config"
SECRETS = f"{INV}/secrets"
PVE_NODES = {"NODE1": "10.0.0.50", "NODE2": "10.0.0.40", "NODE3": "10.0.0.10",
             "NODE4": "10.0.0.80", "NODE5": "10.0.0.20"}
NODE_ROLE = {"NODE1": "24/7", "NODE2": "24/7", "NODE3": "24/7",
             "NODE4": "cold spare", "NODE5": "cold spare"}
DOCKER = {"squidnode02": ("http://127.0.0.1:2375", "CT104"), "squidnode01": ("http://10.0.0.85:2375", "CT116")}
PIHOLE = "http://10.0.0.61/api"
NETALERTX_CONF = f"{BASE}/netalertx/config/app.conf"
STALE_DAYS = 30
UID = GID = 1000          # Homepage runs as PUID/PGID 1000
CTX = ssl._create_unverified_context()   # PVE uses its own CA; LAN only


def load(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def http(url, headers=None, data=None, method=None, timeout=10):
    req = urllib.request.Request(url, headers=headers or {}, data=data, method=method)
    with urllib.request.urlopen(req, timeout=timeout, context=CTX if url.startswith("https") else None) as r:
        body = r.read()
        return json.loads(body) if body else None


def card(name, **kw):
    return {name: {k: v for k, v in kw.items() if v not in (None, "")}}


def error_card(what, err):
    return card(f"{what} unavailable", icon="mdi-alert", description=f"{type(err).__name__}: {str(err)[:120]}")


def octet_ok(ip):
    last = int(ip.rsplit(".", 1)[1])
    return last % 5 == 0


# ---------------- Proxmox ----------------
def proxmox(links):
    tok = load(f"{SECRETS}/pve-token.json")
    auth = {"Authorization": f"PVEAPIToken={tok['full-tokenid']}={tok['value']}"}
    api = "https://10.0.0.50:8006/api2/json"
    res = http(f"{api}/cluster/resources", auth)["data"]
    nodes = {r["node"]: r.get("status") for r in res if r["type"] == "node"}
    guests = [r for r in res if r["type"] in ("lxc", "qemu")]
    macs = {}   # mac -> "CT 104 squidnode02"
    groups = {}
    for g in sorted(guests, key=lambda r: r["vmid"]):
        node, vmid, typ = g["node"], g["vmid"], g["type"]
        kind = "LXC" if typ == "lxc" else "VM"
        ip, ipsrc = "", ""
        try:
            conf = http(f"{api}/nodes/{node}/{typ}/{vmid}/config", auth)["data"]
        except Exception:
            conf = {}
        for k in sorted(conf):
            if not k.startswith("net"):
                continue
            parts = dict(p.split("=", 1) for p in conf[k].split(",") if "=" in p)
            mac = parts.get("hwaddr") or next((v for kk, v in parts.items() if kk in ("virtio", "e1000", "vmxnet3", "rtl8139")), "")
            if mac:
                macs[mac.lower()] = f"{kind} {vmid} {g.get('name', '')}"
            if typ == "lxc" and not ip and parts.get("ip") not in (None, "dhcp", "manual"):
                ip, ipsrc = parts["ip"].split("/")[0], "static"
        if not ip and typ == "lxc" and g.get("status") == "running" and nodes.get(node) == "online":
            try:
                for itf in http(f"{api}/nodes/{node}/lxc/{vmid}/interfaces", auth)["data"] or []:
                    a = (itf.get("inet") or "").split("/")[0]
                    if itf.get("name") != "lo" and a.startswith("10."):
                        ip, ipsrc = a, "dhcp"
                        break
            except Exception:
                pass
        g["_ip"], g["_ipsrc"], g["_mac"] = ip, ipsrc, [m for m, v in macs.items() if v.startswith(f"{kind} {vmid} ")]
        tags = (g.get("tags") or "").replace(";", ", ")
        desc = " · ".join(x for x in [kind, ip or "no IP yet", tags] if x)
        live = nodes.get(node) == "online"
        if not live:
            desc += " · node off"
        entry = dict(icon="mdi-cube-outline" if kind == "LXC" else "mdi-monitor", description=desc,
                     href=links.get(ip, {}).get("href"))
        if live:
            entry.update(proxmoxNode=node, proxmoxVMID=vmid, proxmoxType=typ)
        gname = f"{node} ({NODE_ROLE.get(node, '')}{'' if live else ', off'})"
        groups.setdefault(gname, []).append(card(f"{vmid} {g.get('name', '')}", **entry))
    order = sorted(groups, key=lambda n: (NODE_ROLE.get(n.split()[0]) != "24/7", n))
    return [{n: groups[n]} for n in order], macs, guests


# ---------------- Docker ----------------
def docker():
    out = []
    for server, (url, ct) in DOCKER.items():
        try:
            cs = http(f"{url}/containers/json?all=1")
            items = [card(c["Names"][0].lstrip("/"), icon="mdi-docker", server=server,
                          container=c["Names"][0].lstrip("/"), description=c["Image"].split("@")[0][-60:])
                     for c in sorted(cs, key=lambda c: c["Names"][0])]
        except Exception as e:
            items = [error_card(f"Docker on {server}", e)]
        out.append({f"Docker · {server} ({ct})": items})
    return out


# ---------------- Pi-hole ----------------
def pihole(macs, names, links):
    pw_file = f"{SECRETS}/pihole-app-password"
    if not os.path.exists(pw_file):
        return [{"Network": [card("Waiting for Pi-hole app password", icon="mdi-key-alert",
                                  description=f"Put it in {pw_file} (root, mode 600)")]}]
    pw = open(pw_file).read().strip()
    sid = http(f"{PIHOLE}/auth", {"Content-Type": "application/json"},
               json.dumps({"password": pw}).encode())["session"]["sid"]
    try:
        devs = http(f"{PIHOLE}/network/devices?max_devices=1000&max_addresses=50", {"X-FTL-SID": sid})["devices"]
    finally:
        try:
            http(f"{PIHOLE}/auth", {"X-FTL-SID": sid}, method="DELETE")
        except Exception:
            pass
    now = time.time()
    seen = {}
    for d in devs:
        mac = (d.get("hwaddr") or "").lower()
        for a in d.get("ips") or []:
            ip = a.get("ip", "")
            if not ip.startswith("10.0."):
                continue
            last = a.get("lastSeen") or d.get("lastQuery") or 0
            if ip in seen and seen[ip]["last"] >= last:
                continue
            seen[ip] = dict(mac=mac, last=last, first=d.get("firstSeen") or 0,
                            vendor=(d.get("macVendor") or "").strip(), pname=a.get("name") or "")
    groups = {"Network · static (10.0.0.x)": [], "Network · static overflow (10.0.1.x)": [],
              "Network · DHCP pool (10.0.2.x)": [],
              "Network · other ranges": [], f"Network · not seen for {STALE_DAYS}+ days": []}
    for ip in sorted(seen, key=lambda s: tuple(int(p) for p in s.split("."))):
        s = seen[ip]
        name = macs.get(s["mac"]) or names.get(s["mac"]) or s["pname"] or s["vendor"] or "unknown"
        day = datetime.date.fromtimestamp(s["last"]).isoformat() if s["last"] else "?"
        bits = [s["mac"].upper(), s["vendor"], f"last seen {day}"]
        stale = s["last"] and now - s["last"] > STALE_DAYS * 86400
        if (ip.startswith("10.0.0.") or ip.startswith("10.0.1.")) and ip != "10.0.0.1" and not octet_ok(ip):
            bits.append("⚠ not x0/x5")
        if stale:
            g = f"Network · not seen for {STALE_DAYS}+ days"
        elif ip.startswith("10.0.0."):
            g = "Network · static (10.0.0.x)"
        elif ip.startswith("10.0.1."):
            g = "Network · static overflow (10.0.1.x)"
        elif ip.startswith("10.0.2."):
            g = "Network · DHCP pool (10.0.2.x)"
        else:
            g = "Network · other ranges"
        groups[g].append(card(f"{ip}  {name}", icon="mdi-lan-connect" if not stale else "mdi-lan-disconnect",
                              description=" · ".join(b for b in bits if b), href=links.get(ip, {}).get("href")))
    return [{k: v} for k, v in groups.items() if v]


# ---------------- NetAlertX widget key ----------------
def netalertx_key():
    """API_TOKEN: app.conf if set there, else NetAlertX's effective settings (inside the container)."""
    try:
        for line in open(NETALERTX_CONF):
            if line.startswith("API_TOKEN"):
                return line.split("=", 1)[1].strip().strip("'\"")
    except FileNotFoundError:
        pass
    try:
        import subprocess
        out = subprocess.run(["docker", "exec", "netalertx", "cat", "/tmp/api/table_settings.json"],
                             capture_output=True, timeout=20, check=True).stdout
        for r in json.loads(out)["data"]:
            if r["setKey"] == "API_TOKEN" and r["setValue"]:
                return str(r["setValue"])
    except Exception:
        pass
    return None


def write_atomic(path, obj):
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.chown(tmp, UID, GID)
    os.chmod(tmp, 0o640)
    os.replace(tmp, path)


def main():
    links = load(f"{INV}/links.json", {})
    names = {k.lower(): v for k, v in load(f"{INV}/names.json", {}).items()}
    static = load(f"{INV}/static_services.json", [])
    base = load(f"{INV}/settings_base.json", {})
    problems = []

    key = netalertx_key()
    for grp in static:                       # inject the NetAlertX widget key, if NetAlertX is up
        for items in grp.values():
            for it in items:
                for svc in it.values():
                    w = svc.get("widget")
                    if w and w.get("type") == "netalertx":
                        if key:
                            w["key"] = key
                        else:
                            svc.pop("widget")

    try:                                     # live Proxmox node widgets; token/secret read from config/proxmox.yaml at runtime
        pmx = json.load(open(f"{CFG}/proxmox.yaml"))
    except Exception:
        pmx = {}
    for grp in static:
        for items in grp.values():
            for it in items:
                for nm, svc in it.items():
                    if nm in pmx and "widget" not in svc and pmx[nm].get("token"):
                        svc["widget"] = {"type": "proxmox", "url": pmx[nm]["url"], "username": pmx[nm]["token"],
                                         "password": pmx[nm]["secret"], "node": nm}

    try:
        guest_groups, macs, _ = proxmox(links)
    except Exception as e:
        guest_groups, macs = [{"Proxmox": [error_card("Proxmox API", e)]}], {}
        problems.append(f"proxmox: {e}")
    docker_groups = docker()
    try:
        net_groups = pihole(macs, names, links)
    except Exception as e:
        net_groups = [{"Network": [error_card("Pi-hole API", e)]}]
        problems.append(f"pihole: {e}")

    services = static + guest_groups + docker_groups + net_groups
    layout = {}
    for tab, groups in (("Home", static), ("Guests", guest_groups + docker_groups), ("Network", net_groups)):
        for grp in groups:
            for gname in grp:
                layout[gname] = dict(tab=tab, style="row", columns=4 if tab != "Network" else 3)
    for gname, extra in (base.pop("layout_overrides", {}) or {}).items():
        if gname in layout:
            layout[gname].update(extra)
    settings = dict(base, layout=layout)
    write_atomic(f"{CFG}/services.yaml", services)
    write_atomic(f"{CFG}/settings.yaml", settings)
    n = sum(len(v) for g in services for v in g.values())
    print(f"ok: {len(services)} groups, {n} cards" + (f"; problems: {problems}" if problems else ""))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
