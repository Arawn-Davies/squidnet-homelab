#!/usr/bin/env python3
"""Preserve everything verify.py could not find in BASE: copy it out of its snapshot into the live archive.

usage: recover.py [--dry-run]
Reads /root/snaprelease-20261106/unmatched.tsv. Destination: /RAID/archive/_snapshot-recovered-20261106/<snapshot>/<path>.
Rows marked cached-unmatched are the same object already copied from an earlier snapshot; they are logged, not re-copied.
Copies keep owner, group, mode and mtime; every copied file is byte-compared against its snapshot source afterwards.
Never overwrites: refuses if a destination path already exists.
"""
import os, shutil, stat, sys
SNAP = b"/RAID/archive/.zfs/snapshot/"
DEST = b"/RAID/archive/_snapshot-recovered-20261106/"
OUT = "/root/snaprelease-20261106"
dry = "--dry-run" in sys.argv
rows = [l.rstrip(b"\n").split(b"\t") for l in open(f"{OUT}/unmatched.tsv", "rb")][1:]
need = sum(int(r[3]) for r in rows if r[2] == b"file" and r[4] != b"cached-unmatched")
st = os.statvfs("/RAID/archive"); free = st.f_bavail * st.f_frsize
print(f"rows={len(rows)} to-copy-bytes={need/1e9:.2f} GB free={free/1e9:.1f} GB dry={dry}")
if need > free * 0.5: sys.exit("refusing: would use over half the free space")
log = open(f"{OUT}/recovered.tsv", "ab")
def same(a, b):
    with open(a, "rb") as x, open(b, "rb") as y:
        while True:
            p, q = x.read(8 << 20), y.read(8 << 20)
            if p != q: return False
            if not p: return True
done = bad = 0
for snap, path, ty, size, reason in rows:
    src = SNAP + snap + b"/" + path; dst = DEST + snap + b"/" + path
    if reason == b"cached-unmatched":
        log.write(b"\t".join([snap, path, b"same-object-as-earlier-snapshot-copy"]) + b"\n"); continue
    if os.path.lexists(dst): sys.exit(f"refusing: {dst!r} exists")
    if dry: print("would copy", ty.decode(), size.decode(), src.decode(errors="replace")); continue
    s = os.lstat(src)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if ty == b"dir":
        os.makedirs(dst, exist_ok=True)
    elif ty == b"link":
        os.symlink(os.readlink(src), dst); os.lchown(dst, s.st_uid, s.st_gid)
    elif ty == b"file":
        shutil.copy2(src, dst, follow_symlinks=False); os.chown(dst, s.st_uid, s.st_gid); os.chmod(dst, stat.S_IMODE(s.st_mode))
        os.utime(dst, ns=(s.st_atime_ns, s.st_mtime_ns))
        if not same(src, dst): bad += 1; print("VERIFY FAILED", dst.decode(errors="replace")); continue
    else:
        print("skipped special file type", ty.decode(), src.decode(errors="replace")); bad += 1; continue
    done += 1; log.write(b"\t".join([snap, path, b"copied-and-verified"]) + b"\n")
print(f"copied+verified={done} failed={bad}")
sys.exit(1 if bad else 0)
