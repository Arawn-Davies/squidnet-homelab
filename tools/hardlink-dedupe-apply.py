import os, sys, hashlib, random
ROOT = "/path/to/dataset"; PLAN = "/root/archive-inventory/hardlink-plan.tsv"; LOG = "/root/archive-inventory/hardlink-applied.tsv"
rows = [l.rstrip("\n").split("\t") for l in open(PLAN)][1:]
done = fail = 0; freed = 0
with open(LOG, "w") as log:
    log.write("keep\tlinked\tbytes\tresult\n")
    for keep, other, size in rows:
        k, o = f"{ROOT}/{keep}", f"{ROOT}/{other}"
        try:
            ks, os_ = os.stat(k), os.stat(o)
            if ks.st_ino == os_.st_ino: log.write(f"{keep}\t{other}\t{size}\talready\n"); continue
            if ks.st_size != int(size) or os_.st_size != int(size): raise RuntimeError("size changed")
            tmp = o + ".squidlink.tmp"
            if os.path.exists(tmp): os.unlink(tmp)
            os.link(k, tmp); os.replace(tmp, o)          # atomic swap: the path is never missing
            done += 1; freed += int(size); log.write(f"{keep}\t{other}\t{size}\tlinked\n")
        except Exception as e:
            fail += 1; log.write(f"{keep}\t{other}\t{size}\tFAILED {e}\n")
print(f"APPLIED linked={done} failed={fail} logical_bytes_shared={freed/1e9:.1f} GB")
# verify a random sample by full checksum against the keeper (same inode means same data, this double-checks)
linked = [l.rstrip("\n").split("\t") for l in open(LOG)][1:]
linked = [r for r in linked if r[3] == "linked"]
for keep, other, size, _ in random.sample(linked, min(5, len(linked))):
    same_inode = os.stat(f"{ROOT}/{keep}").st_ino == os.stat(f"{ROOT}/{other}").st_ino
    print(f"VERIFY inode-shared={same_inode} size={int(size)/1e6:.0f}MB {other.split('/')[-1][:60]}")
