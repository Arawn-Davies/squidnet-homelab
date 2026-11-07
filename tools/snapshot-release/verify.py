#!/usr/bin/env python3
"""READ-ONLY verifier: is every byte held by the old RAID/archive snapshots also present in BASE?

usage: verify.py BASE OLD1 [OLD2 ...]     (snapshot names without the dataset prefix)

BASE is a snapshot taken just before this run, so both sides are immutable and nothing can race.
For each OLD snapshot, three independent checks:
  1. zfs diff OLD BASE                  -> every changed / removed / renamed entry
  2. full walk of OLD, lstat against BASE (object id, type, size, mtime) -> every entry that is not
     provably the same unchanged object; cross-checked against (1)
  3. for every entry from (1) or (2): byte-for-byte search for its content in BASE
     (same path, rename target, hard-link keeper from the dedupe logs, moved directory, then any
     same-size file anywhere in BASE)
Anything not found byte-for-byte goes to unmatched.tsv. Original metadata of every candidate goes to
meta.tsv. Files are opened O_RDONLY only; output goes to OUT (on the root filesystem, not the archive).
"""
import collections, json, os, re, stat, subprocess, sys, time

DS = "RAID/archive"
MP = b"/RAID/archive"
SNAP = MP + b"/.zfs/snapshot/"
OUT = "/root/snaprelease-20261106"
LOGS = ["/root/archive-inventory/exodos-hardlink-applied.tsv", "/root/archive-inventory/step2-hardlink-applied.tsv"]
CHUNK = 8 << 20

base, olds = sys.argv[1], sys.argv[2:]
os.makedirs(OUT, exist_ok=True)
plog = open(f"{OUT}/progress.log", "a", buffering=1)
def say(m):
    plog.write(time.strftime("%F %T ") + m + "\n")

def unesc(p):
    return re.sub(rb"\\([0-7]{4})", lambda m: bytes([int(m.group(1), 8)]), p)

def rel(p):
    p = unesc(p)
    if p == MP: return b""
    if not p.startswith(MP + b"/"): raise ValueError(f"unexpected path {p!r}")
    return p[len(MP) + 1:]

def sroot(s): return SNAP + s.encode() + b"/"

def lst(path):
    try: return os.lstat(path)
    except FileNotFoundError: return None

def same_object(a, b):
    return (b is not None and stat.S_IFMT(a.st_mode) == stat.S_IFMT(b.st_mode) and a.st_ino == b.st_ino
            and a.st_size == b.st_size and a.st_mtime_ns == b.st_mtime_ns)

def same_bytes(pa, pb, size):
    fa = os.open(pa, os.O_RDONLY); fb = os.open(pb, os.O_RDONLY)
    try:
        if os.fstat(fa).st_size != size or os.fstat(fb).st_size != size: return False
        while True:
            x = os.read(fa, CHUNK); y = os.read(fb, CHUNK)
            if x != y: return False
            if not x: return True
    finally:
        os.close(fa); os.close(fb)

def content_match(sp, st, bp):
    """Does BASE path bp hold exactly the content of snapshot entry sp?"""
    b = lst(bp)
    if b is None or stat.S_IFMT(b.st_mode) != stat.S_IFMT(st.st_mode): return False
    if stat.S_ISLNK(st.st_mode): return os.readlink(sp) == os.readlink(bp)
    if stat.S_ISREG(st.st_mode): return b.st_size == st.st_size and same_bytes(sp, bp, st.st_size)
    return False

# dedupe-log keeper map: replaced path -> keeper path (both relative to the dataset root)
keeper = {}
for lf in LOGS:
    for line in open(lf, "rb"):
        f = line.rstrip(b"\n").split(b"\t")
        if len(f) == 4 and f[3] == b"linked": keeper[f[1]] = f[0]
say(f"== start base={base} olds={olds} keeper-map={len(keeper)}")

summary = {"base": base, "snapshots": {}}
meta = open(f"{OUT}/meta.tsv", "wb"); meta.write(b"snapshot\tpath\ttype\tsize\tuid\tgid\tmode\tmtime_ns\n")
unm = open(f"{OUT}/unmatched.tsv", "wb"); unm.write(b"snapshot\tpath\ttype\tsize\treason\n")
cache = {}   # (ino, size, mtime_ns, ctime_ns) -> matched?  (same object seen in several snapshots)

for old in olds:
    S = sroot(old); B = sroot(base); t0 = time.time(); R = collections.Counter()
    # ---- check 1: zfs diff
    out = subprocess.run(["zfs", "diff", "-FH", f"{DS}@{old}", f"{DS}@{base}"], capture_output=True, check=True).stdout
    diff = {}; dirmoves = []
    for line in out.splitlines():
        f = line.split(b"\t")
        ch, ft = f[0], f[1]
        if ch == b"+": R["diff_added"] += 1; continue
        if ft == b"/":
            if ch == b"R": dirmoves.append((rel(f[2]) + b"/", rel(f[3]) + b"/"))
            R["diff_dir_entries"] += 1
            if ch == b"-": diff[rel(f[2])] = ("dir-removed", None)
            continue
        p = rel(f[2]); diff[p] = (ch.decode(), rel(f[3]) if ch == b"R" else None)
    R["diff_entries_nondir"] = sum(1 for v in diff.values() if v[0] != "dir-removed")
    say(f"[{old}] zfs diff: {len(out.splitlines())} lines, {len(dirmoves)} dir renames, {dict(R)}")
    def moved(p):
        for a, b in dirmoves:
            if p.startswith(a): return b + p[len(a):]
        return None
    # ---- check 2: full walk
    flagged = set(); nwalk = 0
    for dp, dn, fn in os.walk(S, followlinks=False):
        rd = dp[len(S):]
        for name in fn + [d for d in dn if os.path.islink(os.path.join(dp, d))]:
            r = (rd + b"/" + name) if rd else name
            st = os.lstat(S + r); nwalk += 1
            if not same_object(st, lst(B + r)): flagged.add(r)
            if nwalk % 250000 == 0: say(f"[{old}] walk {nwalk:,} entries, {len(flagged):,} not identical")
        for d in dn:
            if not os.path.lexists(B + ((rd + b"/" + d) if rd else d)) and moved((rd + b"/" + d + b"/") if rd else d + b"/") is None:
                R["walk_dir_missing_in_base"] += 1
    nd = {p for p, v in diff.items() if v[0] != "dir-removed"}
    walk_only = flagged - nd; diff_only = nd - flagged
    R["walk_entries"] = nwalk; R["walk_flagged"] = len(flagged)
    R["walk_flagged_explained_by_dir_rename"] = sum(1 for p in walk_only if moved(p) is not None)
    R["walk_flagged_NOT_in_diff_unexplained"] = sum(1 for p in walk_only if moved(p) is None)
    R["diff_entries_not_flagged_by_walk"] = len(diff_only)
    say(f"[{old}] walk done {nwalk:,} entries in {time.time()-t0:.0f}s; cross-check {dict(R)}")
    with open(f"{OUT}/crosscheck-{old}.tsv", "wb") as cf:
        for p in sorted(walk_only): cf.write(b"walk-only\t" + p + b"\t" + (moved(p) or b"") + b"\n")
        for p in sorted(diff_only): cf.write(b"diff-only\t" + p + b"\t" + diff[p][0].encode() + b"\n")
    # ---- check 3: content search for the union (conservative)
    cand = flagged | nd; want = []
    for i, p in enumerate(sorted(cand)):
        st = os.lstat(S + p)
        ty = "link" if stat.S_ISLNK(st.st_mode) else "file" if stat.S_ISREG(st.st_mode) else oct(stat.S_IFMT(st.st_mode))
        meta.write(b"\t".join([old.encode(), p, ty.encode(), str(st.st_size).encode(), str(st.st_uid).encode(),
                               str(st.st_gid).encode(), oct(st.st_mode & 0o7777).encode(), str(st.st_mtime_ns).encode()]) + b"\n")
        key = (st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns)
        if key in cache:
            R["match_cached_from_other_snapshot" if cache[key] else "unmatched_cached"] += 1
            if not cache[key]: unm.write(b"\t".join([old.encode(), p, ty.encode(), str(st.st_size).encode(), b"cached-unmatched"]) + b"\n")
            continue
        tries = [("same_path", p), ("rename", diff.get(p, (None, None))[1]), ("hardlink_keeper", keeper.get(p)), ("dir_move", moved(p))]
        hit = None
        for how, q in tries:
            if q is not None and content_match(S + p, st, B + q): hit = how; break
        if hit: R[f"match_{hit}"] += 1; cache[key] = True
        else: want.append((p, st, ty, key))
        if (i + 1) % 2000 == 0: say(f"[{old}] content {i+1:,}/{len(cand):,} {dict((k, v) for k, v in R.items() if k.startswith('match'))}")
    # last resort: any same-size file anywhere in BASE
    if want:
        sizes = {st.st_size for _, st, ty, _ in want if ty == "file"}
        say(f"[{old}] {len(want)} not found at expected places; scanning BASE for {len(sizes)} sizes")
        bysize = collections.defaultdict(list)
        for dp, dn, fn in os.walk(B, followlinks=False):
            for name in fn:
                q = os.path.join(dp, name)
                try: s = os.lstat(q)
                except OSError: continue
                if stat.S_ISREG(s.st_mode) and s.st_size in sizes: bysize[s.st_size].append(q)
        for p, st, ty, key in want:
            ok = ty == "file" and any(same_bytes(S + p, q, st.st_size) for q in bysize.get(st.st_size, []))
            cache[key] = ok
            if ok: R["match_same_size_elsewhere"] += 1
            else:
                R["UNMATCHED"] += 1
                unm.write(b"\t".join([old.encode(), p, ty.encode(), str(st.st_size).encode(), b"no-identical-content-in-base"]) + b"\n")
    for p, v in diff.items():
        if v[0] == "dir-removed" and moved(p + b"/") is None:
            R["dirs_removed"] += 1; unm.write(b"\t".join([old.encode(), p, b"dir", b"0", b"directory-removed"]) + b"\n")
    R["seconds"] = int(time.time() - t0)
    summary["snapshots"][old] = dict(R); say(f"[{old}] DONE {dict(R)}")
    meta.flush(); unm.flush()
    json.dump(summary, open(f"{OUT}/summary.json", "w"), indent=1)
say("ALL DONE")
