import json, os, collections
ROOT="/path/to/dataset"; D="/root/archive-inventory"
KEEP_PREF=("<KEEPER_PREFIX>/",); LINK_PREF=("<LINK_PREFIX_1>/","<LINK_PREFIX_2>/")
g=json.load(open(f"{D}/dups.json")); plan=[]; skip=collections.Counter(); by=collections.Counter(); byb=collections.Counter()
for x in g:
    targets=[p for p in x["paths"] if p.startswith(LINK_PREF)]
    if not targets: continue
    keeps=[p for p in x["paths"] if p.startswith(KEEP_PREF)]
    if not keeps: skip["no copy in keeper folder (left for step 3)"]+=1; continue
    keep=sorted(keeps)[0]
    try: ks=os.stat(f"{ROOT}/{keep}")
    except OSError: skip["keeper moved/missing"]+=1; continue
    if ks.st_size!=x["size"]: skip["keeper size changed"]+=1; continue
    for p in targets:
        try: s=os.stat(f"{ROOT}/{p}")
        except OSError: skip["copy moved/missing"]+=1; continue
        if s.st_ino==ks.st_ino: skip["already linked"]+=1; continue
        if s.st_size!=x["size"]: skip["copy size changed"]+=1; continue
        plan.append((keep,p,x["size"])); k=p.split("/")[0]+"/"+p.split("/")[1]; by[k]+=1; byb[k]+=x["size"]
with open(f"{D}/step2-hardlink-plan.tsv","w") as f:
    f.write("keep\tlink_this\tbytes\n"); [f.write(f"{a}\t{b}\t{c}\n") for a,b,c in plan]
print(f"PLAN: {len(plan)} files, {sum(c for _,_,c in plan)/1e9:.1f} GB would be freed")
for k in by: print(f"  {k}: {by[k]} files, {byb[k]/1e9:.1f} GB")
for k,v in skip.items(): print(f"SKIP {v}: {k}")
for a,b,c in sorted(plan,key=lambda t:-t[2])[:4]: print(f"  e.g. {c/1e9:.2f} GB  {b}  ->  {a}")
