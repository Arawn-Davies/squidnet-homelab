#!/usr/bin/env python3
"""Forward high-severity Suricata alerts (eve.json) to ntfy topic squidnet-ids. Rate-limited, no payloads."""
import json, os, time, urllib.request
EVE="/var/log/suricata/eve.json"; URL="http://10.0.0.205:2586/squidnet-ids"
TOKEN=open("/root/ntfy.token").read().strip()
MAX_SEV=1            # ET Open: 1 = high, 2 = medium, 3 = low
DEDUP=6*3600         # same signature + source: once per 6 h
HOURLY_CAP=20
seen={}; sent=[]
def post(title, msg, prio):
    r=urllib.request.Request(URL, data=msg.encode(), method="POST",
        headers={"Authorization":"Bearer "+TOKEN,"Title":title,"Priority":str(prio),"Tags":"rotating_light,suricata"})
    urllib.request.urlopen(r, timeout=10).read()
def follow(path):
    f=None; ino=None
    while True:
        try:
            st=os.stat(path)
            if f is None or st.st_ino!=ino:
                f=open(path); ino=st.st_ino
                if f is not None and len(seen)==0 and not sent: f.seek(0,2)   # start at the end on first open
            line=f.readline()
            if line: yield line; continue
        except FileNotFoundError:
            pass
        time.sleep(1)
for line in follow(EVE):
    try: e=json.loads(line)
    except ValueError: continue
    if e.get("event_type")!="alert": continue
    a=e.get("alert",{})
    if a.get("severity",3)>MAX_SEV or a.get("action")=="blocked": continue
    now=time.time(); key=(a.get("signature_id"), e.get("src_ip"))
    if now-seen.get(key,0)<DEDUP: continue
    sent[:]=[t for t in sent if now-t<3600]
    if len(sent)>=HOURLY_CAP: continue
    seen[key]=now; sent.append(now)
    msg=f'{a.get("signature")}\n{e.get("src_ip")}:{e.get("src_port","")} -> {e.get("dest_ip")}:{e.get("dest_port","")} {e.get("proto","")}\ncategory: {a.get("category","")} (sid {a.get("signature_id")})'
    try: post(f'IDS: {a.get("category","alert")}', msg, 4)
    except Exception as x: print("ntfy post failed:", x, flush=True)
