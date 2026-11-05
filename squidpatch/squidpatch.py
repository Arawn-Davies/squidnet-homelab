#!/usr/bin/env python3
"""squidpatch: agentless outdated-package dashboard for SQUIDNET (runs on NODE1 as root).

  squidpatch.py serve     HTTP API + UI on :8780 (reachable only from NPM/Homepage via host firewall)
  squidpatch.py collect   probe every running node/CT/VM once and write status.json

Probes only read package metadata (plus `apt-get update`). Upgrade jobs: snapshot first, then
apt full-upgrade with old config files kept. Never reboots. Only allowlisted actions, keyed by
node name / numeric VMID taken from the cluster inventory - no free-form commands.
"""
import datetime, http.server, json, os, re, socketserver, subprocess, sys, threading, time, uuid

BASE = "/opt/squidpatch"; STATE = "/var/lib/squidpatch"; STATUS = f"{STATE}/status.json"; JOBDIR = f"{STATE}/jobs"
PORT = 8780; NPM = "10.0.0.95"; READERS = {"10.0.0.25"}; ADMIN = "akadmin"; ORIGIN = "https://patch.lab.example.co.uk"
SNAP_PREFIX = "patch-"; SNAP_KEEP_DAYS = 7; MAX_JOBS = 2
CRITICAL = re.compile(r"^(openssh-|openssl|libssl|linux-image|pve-kernel|proxmox-kernel|proxmox-ve|sudo$|libc6|libc-bin|"
                      r"systemd|libsystemd|curl|libcurl|gnutls|libgnutls|xz-utils|liblzma|polkit|libpolkit|bash$|"
                      r"openjdk|tomcat|nginx|apache2|samba|libsmb|docker|containerd|runc|qemu-server|pve-container|"
                      r"pve-manager|lxc-pve|zfs|libzfs|cloudflared|crowdsec|vaultwarden|jellyfin)")
EOL = {("debian", "10"): "2024-06-30", ("debian", "11"): "2026-08-31", ("debian", "12"): "2028-06-30",
       ("debian", "13"): "2030-06-30", ("ubuntu", "20.04"): "2025-05-31", ("ubuntu", "22.04"): "2027-06-01",
       ("ubuntu", "24.04"): "2029-05-31", ("ubuntu", "26.04"): "2031-05-31",
       # interim (9-month) releases
       ("ubuntu", "24.10"): "2025-07-10", ("ubuntu", "25.04"): "2026-01-15", ("ubuntu", "25.10"): "2026-07-09"}
APT_UPGRADE = ("export DEBIAN_FRONTEND=noninteractive LANG=C; apt-get update -q && "
               "apt-get -y -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold full-upgrade; "
               "rc=$?; echo; echo SQUIDPATCH_EXIT=$rc; [ -f /var/run/reboot-required ] && echo 'NOTE: reboot required'; exit $rc")
KEY_RE = re.compile(r"^(node:[A-Za-z0-9-]+|ct:\d{3,5}|vm:\d{3,5})$")
os.makedirs(JOBDIR, exist_ok=True)
LOCK = threading.Lock(); HOSTLOCKS = {}; JOBS = {}; COLLECTING = threading.Event()
CHECKLOG = f"{STATE}/check.log"; CLOCK = threading.Lock()
CHECK = {"start": None, "end": None, "by": None, "scope": None, "total": 0, "done": 0, "failed": 0, "current": []}
LOCAL = os.uname().nodename

def now(): return int(time.time())

def members():
    m = json.load(open("/etc/pve/.members"))
    return {n: v for n, v in m["nodelist"].items()}

def run_on(node, cmd, stdin=None, timeout=900):
    """Run a shell command on a cluster node (locally or via the cluster SSH hop)."""
    if node == LOCAL:
        argv = ["bash", "-c", cmd]
    else:
        ip = members()[node]["ip"]
        argv = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", f"HostKeyAlias={node}",
                "-o", f"UserKnownHostsFile=/etc/pve/nodes/{node}/ssh_known_hosts", f"root@{ip}", cmd]
    p = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout)
    return p.returncode, p.stdout, p.stderr

def inventory():
    out = subprocess.run(["pvesh", "get", "/cluster/resources", "--output-format", "json"], capture_output=True, text=True, timeout=60).stdout
    res = json.loads(out); mem = members(); items = []
    for n, v in sorted(mem.items()):
        items.append({"key": f"node:{n}", "kind": "node", "id": n, "name": n, "node": n, "state": "online" if v.get("online") else "offline"})
    for r in res:
        if r.get("type") in ("lxc", "qemu") and not r.get("template"):
            k = "ct" if r["type"] == "lxc" else "vm"
            items.append({"key": f"{k}:{r['vmid']}", "kind": k, "id": r["vmid"], "name": r.get("name", ""), "node": r["node"], "state": r.get("status", "unknown")})
    return items

def vm_conf(node, vmid):
    rc, out, _ = run_on(node, f"qm config {int(vmid)}", timeout=60)
    return out if rc == 0 else ""

def probe(item):
    probe_sh = open(f"{BASE}/probe.sh").read()
    k, node = item["kind"], item["node"]
    if k == "node":
        rc, out, err = run_on(node, "sh -s", stdin=probe_sh, timeout=600)
    elif k == "ct":
        rc, out, err = run_on(node, f"pct exec {int(item['id'])} -- sh -s", stdin=probe_sh, timeout=600)
    else:
        conf = vm_conf(node, item["id"])
        if re.search(r"^ostype: (win|w2k|wxp|wvista|other)", conf, re.M):
            return {"ok": False, "skip": True, "error": "not Linux - not checked"}
        if not re.search(r"^agent: (1|enabled=1)", conf, re.M):
            return {"ok": False, "skip": True, "error": "no QEMU guest agent - can't check"}
        rc, out, err = run_on(node, f"qm guest exec {int(item['id'])} --timeout 600 --pass-stdin 1 -- sh -s", stdin=probe_sh, timeout=660)
        if rc == 0:
            try:
                j = json.loads(out); out = j.get("out-data", ""); rc = j.get("exitcode", 1)
            except ValueError:
                rc = 1
    if "##END" not in out:
        return {"ok": False, "error": (err or out or f"exit {rc}").strip().splitlines()[-1][:200] if (err or out) else f"exit {rc}"}
    return parse(out)

def parse(out):
    sec, cur = {}, None
    for line in out.splitlines():
        if line.startswith("##"):
            parts = line[2:].split(" ", 1); cur = parts[0]; sec[cur] = [parts[1]] if len(parts) > 1 else []
        elif cur:
            sec[cur].append(line)
    osf = (sec.get("OS", ["|||"])[0] + "|||").split("|")
    d = {"ok": True, "os": {"id": osf[0], "version": osf[1], "pretty": osf[2], "codename": osf[3]},
         "kernel": (sec.get("KERNEL") or [""])[0], "pm": (sec.get("PM") or ["none"])[0]}
    if sec.get("PVE"): d["platform"] = sec["PVE"][0]
    if sec.get("PBS"): d["platform"] = sec["PBS"][0]
    eol = EOL.get((d["os"]["id"], d["os"]["version"]))
    if eol:
        days = (datetime.date.fromisoformat(eol) - datetime.date.today()).days
        d["eol"] = {"date": eol, "days": days, "status": "eol" if days < 0 else ("soon" if days < 180 else "ok")}
    upd = sec.get("UPDATE", [])
    d["update_rc"] = int(upd[0].split("=")[1]) if upd and upd[0].startswith("rc=") else None
    d["update_warn"] = [l for l in upd[1:] if l.strip()][:3]
    kept = set(l.strip() for l in sec.get("KEPT", []) if l.strip())
    pk = []
    for l in sec.get("UPG", []):
        m = re.match(r"^(\S+?)/(\S+)\s+(\S+)\s+(\S+)(?:\s+\[upgradable from: (\S+)\])?", l)
        if not m: continue
        name, suites, new, _arch, old = m.groups()
        security = "security" in suites
        pk.append({"name": name, "old": old or "", "new": new, "suites": suites, "security": security,
                   "critical": bool(security and CRITICAL.match(name)), "kept": name in kept})
    d["packages"] = sorted(pk, key=lambda p: (not p["critical"], not p["security"], p["name"]))
    rb = sec.get("REBOOT", ["no"])
    d["reboot"] = bool(rb and rb[0] == "yes"); d["reboot_pkgs"] = (rb[1].split() if len(rb) > 1 else [])[:10]
    nk = (sec.get("NEWEST_KERNEL") or [""])[0].strip()
    if nk and d["kernel"] and nk != d["kernel"] and d.get("platform"):
        d["reboot"] = True; d["reboot_pkgs"] = [f"kernel {nk} installed, running {d['kernel']}"]
    auto = (sec.get("AUTO") or [""])
    d["unattended"] = bool(auto and auto[0].strip() not in ("", "0"))
    d["counts"] = {"total": len(pk), "security": sum(p["security"] for p in pk), "critical": sum(p["critical"] for p in pk),
                   "kept": sum(p["kept"] for p in pk)}
    return d

def load_status():
    try: return json.load(open(STATUS))
    except (OSError, ValueError): return {"generated": 0, "hosts": {}}

def save_status(st):
    tmp = STATUS + ".tmp"; json.dump(st, open(tmp, "w")); os.replace(tmp, STATUS)

def clog(msg):
    with CLOCK:
        with open(CHECKLOG, "a") as f: f.write(time.strftime("%H:%M:%S ") + msg + "\n")

def result_line(r):
    if not r.get("ok"): return ("skipped: " if r.get("skip") else "FAILED: ") + str(r.get("error", ""))
    c = r["counts"]; o = [f"{c['total']} updates"]
    if c["security"]: o.append(f"{c['security']} security")
    if c["critical"]: o.append(f"{c['critical']} CRITICAL")
    if c.get("kept"): o.append(f"{c['kept']} held")
    if r.get("reboot"): o.append("reboot needed")
    return "ok - " + ", ".join(o)

def collect(keys=None, by="timer"):
    """Probe running hosts (all, or just `keys`). Nodes run in parallel; guests on a node sequentially."""
    COLLECTING.set(); t0 = time.time()
    with CLOCK:
        open(CHECKLOG, "w").close()
        CHECK.update({"start": now(), "end": None, "by": by, "scope": "all" if keys is None else ",".join(sorted(keys)),
                      "total": 0, "done": 0, "failed": 0, "current": []})
    try:
        inv = inventory(); st = load_status(); hosts = st.get("hosts", {})
        want = [i for i in inv if keys is None or i["key"] in keys]
        bynode = {}
        for i in want: bynode.setdefault(i["node"], []).append(i)
        n_live = sum(1 for i in want if i["state"] in ("running", "online"))
        with CLOCK: CHECK["total"] = n_live
        clog(f"== check started by {by}: {n_live} running hosts on {len(bynode)} nodes ({CHECK['scope']})")
        def work(items):
            for it in items:
                prev = hosts.get(it["key"], {})
                base = {**it, "checked": prev.get("checked"), "result": prev.get("result")}
                if it["state"] not in ("running", "online"):
                    base["stale"] = True; hosts[it["key"]] = base; continue
                label = f"{it['node']} {it['key']} {it.get('name') or ''}".strip()
                with CLOCK: CHECK["current"].append(it["key"])
                ts = time.time()
                try:
                    r = probe(it)
                except Exception as e:  # timeout etc.
                    r = {"ok": False, "error": f"{type(e).__name__}: {e}"[:200]}
                with CLOCK:
                    CHECK["current"].remove(it["key"]); CHECK["done"] += 1
                    if not r.get("ok") and not r.get("skip"): CHECK["failed"] += 1
                    d = CHECK["done"]
                clog(f"[{d}/{n_live}] {label}: {result_line(r)} ({time.time() - ts:.0f}s)")
                base.update({"checked": now(), "result": r, "stale": False}); hosts[it["key"]] = base
        ths = [threading.Thread(target=work, args=(v,)) for v in bynode.values()]
        [t.start() for t in ths]; [t.join() for t in ths]
        live = {i["key"] for i in inv}
        for k in list(hosts):
            if k not in live: del hosts[k]
            else: hosts[k].update({x: y for x, y in next(i for i in inv if i["key"] == k).items()})
        st = {"generated": now(), "hosts": hosts}; save_status(st)
        clog(f"== finished: {CHECK['done']} checked, {CHECK['failed']} failed, {time.time() - t0:.0f}s")
        prune_snapshots(inv)
        return st
    except Exception as e:
        clog(f"== check aborted: {type(e).__name__}: {e}"); raise
    finally:
        with CLOCK: CHECK["end"] = now(); CHECK["current"] = []
        COLLECTING.clear()

def prune_snapshots(inv):
    cutoff = datetime.datetime.now() - datetime.timedelta(days=SNAP_KEEP_DAYS)
    for it in inv:
        if it["kind"] not in ("ct", "vm"): continue
        tool = "pct" if it["kind"] == "ct" else "qm"
        try:
            rc, out, _ = run_on(it["node"], f"{tool} listsnapshot {int(it['id'])}", timeout=60)
        except Exception:
            continue
        for m in re.finditer(rf"({SNAP_PREFIX}(\d{{8}})-(\d{{4}})(\d{{2}})?)\b", out):
            when = datetime.datetime.strptime(m.group(2) + m.group(3), "%Y%m%d%H%M")
            if when < cutoff:
                run_on(it["node"], f"{tool} delsnapshot {int(it['id'])} {m.group(1)}", timeout=300)

    # rootfs-only fallback snapshots (CTs with bind mounts): ZFS datasets and LVM-thin LVs named *patch-YYYYmmdd-HHMM
    for node in sorted({i["node"] for i in inv if i["kind"] == "node" and i["state"] == "online"}):
        try:
            _, out, _ = run_on(node, "zfs list -H -t snapshot -o name 2>/dev/null | grep '@patch-'; "
                                     "lvs --noheadings -o vg_name,lv_name 2>/dev/null | awk '$2 ~ /-patch-[0-9]{8}-[0-9]{4}([0-9]{2})?$/{print $1\"/\"$2}'", timeout=60)
        except Exception:
            continue
        for name in out.split():
            m = re.search(r"patch-(\d{8})-(\d{4})(\d{2})?$", name)
            if not m or not SAFE_NAME.match(name): continue
            if datetime.datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M") >= cutoff: continue
            run_on(node, f"zfs destroy {name}" if "@" in name else f"lvremove -y {name}", timeout=300)

SAFE_NAME = re.compile(r"^[A-Za-z0-9._/@-]+$")

def storage_info():
    """Parse /etc/pve/storage.cfg into {storage_id: {type, pool, vgname, ...}}."""
    info, cur = {}, None
    for line in open("/etc/pve/storage.cfg"):
        m = re.match(r"^(\w+):\s*(\S+)", line)
        if m: cur = m.group(2); info[cur] = {"type": m.group(1)}; continue
        m = re.match(r"^\s+(\S+)\s+(.*)$", line)
        if m and cur: info[cur][m.group(1)] = m.group(2).strip()
    return info

def rootfs_snapshot(node, ctid, snap):
    """Storage-level snapshot of a CT's root disk only (used when pct snapshot refuses, e.g. bind mounts).
    Returns (ok, message, rollback_command)."""
    rc, out, _ = run_on(node, f"pct config {int(ctid)}", timeout=60)
    m = re.search(r"^rootfs:\s*([^:,\s]+):([^,\s]+)", out, re.M)
    if not m: return False, "can't read rootfs", None
    sid, vol = m.group(1), m.group(2)
    st = storage_info().get(sid, {})
    run_on(node, f"pct exec {int(ctid)} -- sync </dev/null", timeout=120)
    if st.get("type") == "zfspool" and st.get("pool"):
        ds = f"{st['pool']}/{vol}"
        if not SAFE_NAME.match(ds): return False, "unexpected dataset name", None
        rc, o, e = run_on(node, f"zfs snapshot {ds}@{snap}", timeout=300)
        return rc == 0, (o + e).strip() or f"zfs snapshot {ds}@{snap}", f"pct stop {int(ctid)} && zfs rollback -r {ds}@{snap} && pct start {int(ctid)}"
    if st.get("type") == "lvmthin" and st.get("vgname"):
        lv = f"{vol}-{snap}"
        if not SAFE_NAME.match(st["vgname"] + lv): return False, "unexpected LV name", None
        rc, o, e = run_on(node, f"lvcreate -s -n {lv} {st['vgname']}/{vol}", timeout=300)
        return rc == 0, (o + e).strip(), f"pct stop {int(ctid)} && lvconvert --merge {st['vgname']}/{lv} && pct start {int(ctid)}"
    return False, f"storage '{sid}' ({st.get('type','?')}) has no snapshot support", None

# ---------------- upgrade jobs ----------------
def job_log(jid, msg):
    with open(f"{JOBDIR}/{jid}.log", "a") as f: f.write(msg if msg.endswith("\n") else msg + "\n")

def run_job(jid, item, force):
    j = JOBS[jid]; key = item["key"]; node = item["node"]
    lock = HOSTLOCKS.setdefault(key, threading.Lock())
    if not lock.acquire(blocking=False):
        j.update(status="failed", end=now()); job_log(jid, "another job is already running on this host"); return
    try:
        j["status"] = "running"
        job_log(jid, f"== {key} ({item['name']}) on {node} - started {time.strftime('%F %T')} by {j['user']}")
        if item["kind"] in ("ct", "vm"):
            tool = "pct" if item["kind"] == "ct" else "qm"
            snap = f"{SNAP_PREFIX}{time.strftime('%Y%m%d-%H%M%S')}"   # seconds: CTs can share a volume (e.g. a disk mounted in two CTs)
            job_log(jid, f"-- snapshot {snap}")
            rc, out, err = run_on(node, f"{tool} snapshot {int(item['id'])} {snap} --description 'squidpatch pre-upgrade'", timeout=900)
            job_log(jid, (out + err).strip() or "ok")
            if rc != 0 and item["kind"] == "ct" and "snapshot feature is not available" in (out + err):
                job_log(jid, "-- Proxmox can't snapshot this CT (bind mounts / storage). Taking a rootfs-only storage snapshot instead;")
                job_log(jid, "   bind-mounted data is not included (apt never touches it).")
                ok, msg, rb = rootfs_snapshot(node, item["id"], snap)
                job_log(jid, msg or "ok")
                if ok:
                    rc = 0; out = err = ""
                    job_log(jid, f"   to roll back: {rb}")
            if rc != 0:
                if not force:
                    j.update(status="failed", end=now()); job_log(jid, f"snapshot failed ({(err or out).strip()[:200]}) - NOT upgrading. Fix that, or use 'upgrade without snapshot' if you accept the risk."); return
                job_log(jid, "snapshot failed, continuing because 'without snapshot' was chosen")
            else:
                j["snapshot"] = snap
        else:
            job_log(jid, "-- node: no snapshot possible for a Proxmox host; config files are kept (confold)")
        if item["kind"] == "node":
            cmd = APT_UPGRADE
        elif item["kind"] == "ct":
            cmd = f"pct exec {int(item['id'])} -- bash -c {sh_quote(APT_UPGRADE)}"
        else:
            cmd = f"qm guest exec {int(item['id'])} --timeout 3500 -- bash -c {sh_quote(APT_UPGRADE)}"
        job_log(jid, "-- apt full-upgrade")
        p = subprocess.Popen(ssh_argv(node, cmd), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in p.stdout:
            job_log(jid, line.rstrip("\n"))
        p.wait(timeout=3600)
        out_ok = p.returncode == 0
        if item["kind"] == "vm":  # qm guest exec returns JSON; exit code is inside
            txt = open(f"{JOBDIR}/{jid}.log").read(); out_ok = '"exitcode" : 0' in txt or '"exitcode": 0' in txt
        j.update(status="done" if out_ok else "failed", end=now())
        job_log(jid, f"== finished {time.strftime('%F %T')}: {'OK' if out_ok else 'FAILED'} (no reboot done)")
    except Exception as e:
        j.update(status="failed", end=now()); job_log(jid, f"error: {e}")
    finally:
        lock.release()
        threading.Thread(target=collect, args=({key},), daemon=True).start()

def sh_quote(s): return "'" + s.replace("'", "'\"'\"'") + "'"

def ssh_argv(node, cmd):
    if node == LOCAL: return ["bash", "-c", cmd]
    ip = members()[node]["ip"]
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", f"HostKeyAlias={node}",
            "-o", f"UserKnownHostsFile=/etc/pve/nodes/{node}/ssh_known_hosts", f"root@{ip}", cmd]

# ---------------- HTTP ----------------
def summary():
    st = load_status(); hs = [h for h in st["hosts"].values() if h.get("result")]
    res = [h["result"] for h in hs if h["result"].get("ok")]
    att = [h for h in hs if (h["result"].get("ok") and (h["result"]["counts"]["security"] or h["result"].get("reboot") or
           (h["result"].get("eol") or {}).get("status") in ("eol", "soon"))) or (not h["result"].get("ok") and not h["result"].get("skip"))]
    return {"hosts": len(st["hosts"]), "checked": len(res), "outdated": sum(r["counts"]["total"] for r in res),
            "security": sum(r["counts"]["security"] for r in res), "critical": sum(r["counts"]["critical"] for r in res),
            "reboot": sum(1 for r in res if r.get("reboot")), "attention": len(att),
            "failed": sum(1 for h in hs if not h["result"].get("ok") and not h["result"].get("skip")),
            "generated": st.get("generated", 0)}

def metrics():
    st = load_status(); L = []
    def lab(h): return f'host="{h["name"] or h["id"]}",key="{h["key"]}",node="{h["node"]}",kind="{h["kind"]}"'
    L += ["# HELP squidpatch_upgradable Packages with updates available", "# TYPE squidpatch_upgradable gauge"]
    for h in st["hosts"].values():
        r = h.get("result") or {}
        if r.get("ok"):
            L.append(f'squidpatch_upgradable{{{lab(h)}}} {r["counts"]["total"]}')
            L.append(f'squidpatch_security_updates{{{lab(h)}}} {r["counts"]["security"]}')
            L.append(f'squidpatch_critical_updates{{{lab(h)}}} {r["counts"]["critical"]}')
            L.append(f'squidpatch_reboot_required{{{lab(h)}}} {int(bool(r.get("reboot")))}')
            if r.get("eol"): L.append(f'squidpatch_os_eol_days{{{lab(h)}}} {r["eol"]["days"]}')
        if h.get("checked"): L.append(f'squidpatch_last_check_timestamp{{{lab(h)}}} {h["checked"]}')
        if not h.get("stale") and r and not r.get("skip"): L.append(f'squidpatch_check_ok{{{lab(h)}}} {int(bool(r.get("ok")))}')
    s = summary()
    for k in ("outdated", "security", "critical", "reboot", "attention", "failed"):
        L.append(f"squidpatch_total_{k} {s[k]}")
    L.append(f'squidpatch_generated_timestamp {s["generated"]}')
    return "\n".join(L) + "\n"

class H(http.server.BaseHTTPRequestHandler):
    server_version = "squidpatch"
    def log_message(self, fmt, *a): sys.stderr.write("%s %s %s\n" % (self.client_address[0], self.headers.get("X-authentik-username", "-"), fmt % a))
    def send(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else (body if isinstance(body, str) else json.dumps(body)).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY"); self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; img-src 'self' data:")
        self.end_headers(); self.wfile.write(b)
    def who(self):
        ip = self.client_address[0]
        if ip == NPM:
            u = self.headers.get("X-authentik-username", "").strip()
            return ("user", u) if u else (None, None)
        if ip in READERS: return ("reader", None)
        if ip == "127.0.0.1": return ("local", "local")
        return (None, None)
    def do_GET(self):
        role, user = self.who(); p = self.path.split("?")[0]
        if role == "reader" and p in ("/api/summary", "/metrics"): pass
        elif role not in ("user", "local"): return self.send(403, {"error": "forbidden"})
        if p in ("/", "/index.html"): return self.send(200, open(f"{BASE}/index.html", "rb").read(), "text/html; charset=utf-8")
        if p == "/api/status":
            st = load_status(); st["collecting"] = COLLECTING.is_set(); st["user"] = user;
            with CLOCK: st["check"] = {**CHECK, "current": list(CHECK["current"])}
            st["admin"] = user in (ADMIN, "local")
            st["jobs"] = sorted(JOBS.values(), key=lambda j: -j["start"])[:30]; return self.send(200, st)
        if p == "/api/summary": return self.send(200, summary())
        if p == "/metrics": return self.send(200, metrics(), "text/plain; version=0.0.4")
        if p == "/api/check/log":
            try: return self.send(200, open(CHECKLOG, "rb").read(), "text/plain; charset=utf-8")
            except OSError: return self.send(200, b"No check has run since the service started.\n", "text/plain; charset=utf-8")
        m = re.match(r"^/api/jobs/([0-9a-f]{32})/log$", p)
        if m and m.group(1) in JOBS:
            try: return self.send(200, open(f"{JOBDIR}/{m.group(1)}.log", "rb").read(), "text/plain; charset=utf-8")
            except OSError: return self.send(404, {"error": "no log"})
        return self.send(404, {"error": "not found"})
    def do_POST(self):
        role, user = self.who()
        if role == "local": pass
        elif role != "user" or user != ADMIN: return self.send(403, {"error": "forbidden"})
        if self.headers.get("X-Squidpatch") != "1": return self.send(403, {"error": "missing csrf header"})
        o = self.headers.get("Origin")
        if o and o != ORIGIN and role != "local": return self.send(403, {"error": "bad origin"})
        try:
            n = min(int(self.headers.get("Content-Length", "0")), 4096); body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return self.send(400, {"error": "bad json"})
        p = self.path
        if p == "/api/check":
            key = body.get("key")
            if key is not None and not KEY_RE.match(str(key)): return self.send(400, {"error": "bad key"})
            if COLLECTING.is_set(): return self.send(409, {"error": "a check is already running"})
            threading.Thread(target=collect, args=(None if key is None else {key}, "timer" if role == "local" else user), daemon=True).start()
            return self.send(202, {"ok": True})
        if p == "/api/upgrade":
            key = str(body.get("key", ""))
            if not KEY_RE.match(key): return self.send(400, {"error": "bad key"})
            item = next((i for i in inventory() if i["key"] == key), None)
            if not item or item["state"] not in ("running", "online"): return self.send(400, {"error": "unknown or not running"})
            with LOCK:
                if sum(1 for j in JOBS.values() if j["status"] in ("queued", "running")) >= MAX_JOBS:
                    return self.send(409, {"error": f"max {MAX_JOBS} upgrades at once"})
                jid = uuid.uuid4().hex
                JOBS[jid] = {"id": jid, "key": key, "name": item["name"], "node": item["node"], "status": "queued",
                             "start": now(), "end": None, "user": user, "force": bool(body.get("force")), "snapshot": None}
            threading.Thread(target=run_job, args=(jid, item, bool(body.get("force"))), daemon=True).start()
            return self.send(202, {"job": jid})
        return self.send(404, {"error": "not found"})

class Server(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True; allow_reuse_address = True

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "collect":
        s = collect(by="cli"); print(json.dumps(summary()))
    else:
        Server(("0.0.0.0", PORT), H).serve_forever()
