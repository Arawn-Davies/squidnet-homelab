# archive-inventory.py

Read-only inventory of a large archive dataset (games, disc images, ROMs, installers, backups).
Pass 1 classifies every file (disc image / ROM / GOG installer / archive / executable / media…) into `files.tsv`.
Pass 2 finds **exact duplicates by content**: only files sharing a size are hashed (1 MiB head+tail first, then full BLAKE2b) → `dups.json`.
Writes only to the output dir, tolerates files moving mid-scan. Run at idle priority:
`systemd-run -p Nice=19 -p IOSchedulingClass=idle python3 archive-inventory.py /path/to/archive /root/archive-inventory`
Used to plan a no-delete reorganisation: one layout (PC/GOG|DOS|Retail per game, Consoles/<platform>, Mac), CHD for disc images, hard links/block clones for true duplicates.

## Reclaiming duplicates without deleting anything (`hardlink-dedupe-plan.py` / `hardlink-dedupe-apply.py`)
On a single ZFS dataset, content-identical files can become **hard links**: every path keeps working, the data is stored once.
1. `hardlink-dedupe-plan.py` reads `dups.json`, picks a keeper per group (by folder prefix, e.g. the main library), and **re-validates** every file (still present, same size, not already linked) - writes a TSV plan, changes nothing.
2. Take a ZFS snapshot (rollback point), then `hardlink-dedupe-apply.py` links each copy with **link-to-temp + atomic rename** (a path is never missing), logs every action, and spot-checks inodes.
3. Space is only freed when the safety snapshot is destroyed, after checking the affected apps still work.
Caveats: a hard-linked file has one set of metadata (mtime/owner) and editing it changes every path - fine for ROMs/ISOs/archives, not for files apps write to. Real-world run: an eXoDOS package duplicated next to its install (7,168 zips, ~694 GB), then console ROM/ISO copies kept for a PS2's SMB share and a USB stick (~266 GB).
