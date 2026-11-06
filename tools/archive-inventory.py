#!/usr/bin/env python3
"""Read-only inventory of the archive dataset: classify files, find exact duplicates by content.
Writes only to OUT (outside the archive). Tolerates files moving/vanishing mid-scan."""
import os, sys, time, hashlib, json, re, stat
from collections import defaultdict

ROOT = sys.argv[1]; OUT = sys.argv[2]; EXCLUDE = {"homework"}
MIN_DUP = 1 << 20          # only dedupe-check files >= 1 MiB
os.makedirs(OUT, exist_ok=True)
log = open(f"{OUT}/progress.log", "a", buffering=1)
def say(m): log.write(time.strftime("%F %T ") + m + "\n")

EXT = {
 "disc-image": "iso bin cue img mdf mds nrg ccd sub chd cdi gdi toast cso rvz wbfs gcm nsp xci ecm pbp vcd dmg cif b5t b6t isz daa uif".split(),
 "rom": "nes fds sfc smc gb gbc gba n64 z64 v64 md gen smd sms gg pce a26 a52 a78 nds 3ds 32x lnx ws wsc ngp ngc col int vb vec st msa adf d64 t64 tap tzx dsk sna z80 rom mx1 mx2 j64 jag".split(),
 "archive": "zip 7z rar sit sitx hqx cpt lha lzh tar gz tgz bz2 xz arj ace cab".split(),
 "executable": "exe com bat msi pkg sh app".split(),
 "photo": "jpg jpeg heic heif png gif bmp tif tiff raw cr2 cr3 nef arw dng webp".split(),
 "video": "mp4 mov avi mkv 3gp m4v mts m2ts wmv mpg mpeg vob flv webm".split(),
 "audio": "mp3 flac m4a wav ogg aac wma aiff aif opus mid midi".split(),
 "document": "pdf doc docx txt rtf xls xlsx ppt pptx odt ods md csv epub".split(),
}
E2C = {e: c for c, l in EXT.items() for e in l}
GOG = re.compile(r"^(setup_.*\.(exe|bin)|gog_.*\.sh|.*_gog_.*|goggame-\d+\..*)$", re.I)

def classify(path, name):
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if GOG.match(name): return "gog-installer", ext
    return E2C.get(ext, "other"), ext

# ---------- pass 1: walk ----------
t0 = time.time(); n = 0; errs = 0
files = open(f"{OUT}/files.tsv", "w")
files.write("path\tsize\tmtime\text\tcategory\ttop1\ttop2\ttop3\n")
bysize = defaultdict(list)
for dp, dn, fn in os.walk(ROOT, onerror=lambda e: None):
    rel = os.path.relpath(dp, ROOT)
    if rel == ".": dn[:] = [d for d in dn if d not in EXCLUDE]
    for f in fn:
        p = os.path.join(dp, f)
        try:
            st = os.lstat(p)
        except OSError:
            errs += 1; continue
        if not stat.S_ISREG(st.st_mode): continue
        r = os.path.relpath(p, ROOT); parts = r.split(os.sep)
        cat, ext = classify(r, f)
        top = (parts[:-1] + ["", "", ""])[:3]
        files.write("\t".join([r.replace("\t", " "), str(st.st_size), str(int(st.st_mtime)), ext, cat] + top) + "\n")
        if st.st_size >= MIN_DUP: bysize[st.st_size].append((r, st.st_ino))
        n += 1
        if n % 200000 == 0: say(f"pass1: {n} files, {time.time()-t0:.0f}s")
files.close()
say(f"pass1 done: {n} files, {errs} vanished/unreadable, {time.time()-t0:.0f}s")

# ---------- pass 2: duplicates (same size -> partial hash -> full hash) ----------
def hpart(p, size):
    h = hashlib.blake2b(digest_size=16)
    with open(p, "rb") as fh:
        h.update(fh.read(1 << 20))
        if size > 2 << 20: fh.seek(-(1 << 20), 2); h.update(fh.read(1 << 20))
    return h.hexdigest()
def hfull(p):
    h = hashlib.blake2b(digest_size=20)
    with open(p, "rb") as fh:
        for b in iter(lambda: fh.read(4 << 20), b""): h.update(b)
    return h.hexdigest()

cands = {s: l for s, l in bysize.items() if len({i for _, i in l}) > 1}   # ignore existing hardlinks
tot = sum(s * len(l) for s, l in cands.items())
say(f"pass2: {len(cands)} size groups, {sum(len(l) for l in cands.values())} files, {tot/1e12:.2f} TB candidate data")
groups = []; done = 0; t1 = time.time()
for size, lst in sorted(cands.items(), key=lambda x: -x[0]):
    part = defaultdict(list)
    for r, ino in lst:
        try: part[hpart(os.path.join(ROOT, r), size)].append(r)
        except OSError: pass
    for ph, rs in part.items():
        if len(rs) < 2: continue
        full = defaultdict(list)
        for r in rs:
            try: full[hfull(os.path.join(ROOT, r))].append(r)
            except OSError: pass
            done += size
        for fh_, rr in full.items():
            if len(rr) > 1: groups.append({"hash": fh_, "size": size, "paths": sorted(rr)})
    if len(groups) and len(groups) % 500 == 0:
        say(f"pass2: {len(groups)} dup groups, {done/1e12:.2f} TB fully hashed, {time.time()-t1:.0f}s")
json.dump(groups, open(f"{OUT}/dups.json", "w"))
waste = sum(g["size"] * (len(g["paths"]) - 1) for g in groups)
say(f"pass2 done: {len(groups)} duplicate groups, reclaimable {waste/1e12:.3f} TB, {time.time()-t1:.0f}s")
say("ALL DONE")
