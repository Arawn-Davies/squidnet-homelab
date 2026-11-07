#!/usr/bin/env python3
"""Map Steam depot IDs to the app (game) that owns them, by asking Steam itself (anonymous login, PICS product info).

Depot IDs come from LANCache logs (lancache-report.sh). The owner is confirmed from each candidate app's depot list,
not guessed from the number. SteamDB blocks scripts, and steamcmd is 32-bit x86, so this uses the ValvePython `steam`
library. No install on the host - run it in a throwaway container:

  docker run --rm -v "$PWD/steam-depot-names.py:/s.py:ro" python:3.12-slim \
    sh -c "pip install -q --root-user-action=ignore 'steam[client]' >/dev/null 2>&1 && python /s.py 2347770 611671 945361"

Output: depot<TAB>app id<TAB>app name (several owners are joined with ' | ', e.g. shared launcher depots).
Depots owned by an app more than SPAN IDs below them (shared runtimes, some launchers) show as NOT FOUND.
"""
import sys
from steam.client import SteamClient

SPAN = 12  # candidate owners: depot, depot-1 ... depot-(SPAN-1), plus Steamworks Common Redistributables
depots = sorted({int(a) for a in sys.argv[1:] if a.isdigit()})
if not depots:
    sys.exit("usage: steam-depot-names.py DEPOT [DEPOT ...]")
cands = sorted({d - k for d in depots for k in range(SPAN)} | {228980})
c = SteamClient()
if c.anonymous_login() != 1:
    sys.exit("anonymous Steam login failed")
apps = {}
for i in range(0, len(cands), 150):
    apps.update((c.get_product_info(apps=cands[i:i + 150], timeout=90) or {}).get("apps", {}))
owner = {}
for aid, a in apps.items():
    name = a.get("common", {}).get("name", "?")
    for k in (a.get("depots") or {}):
        if k.isdigit() and int(k) in depots:
            owner.setdefault(int(k), []).append(f"{aid}\t{name}")
for d in depots:
    print(f"{d}\t" + (" | ".join(owner[d]) if d in owner else "?\tNOT FOUND"))
c.logout()
