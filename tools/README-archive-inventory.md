# archive-inventory.py

Read-only inventory of a large archive dataset (games, disc images, ROMs, installers, backups).
Pass 1 classifies every file (disc image / ROM / GOG installer / archive / executable / media…) into `files.tsv`.
Pass 2 finds **exact duplicates by content**: only files sharing a size are hashed (1 MiB head+tail first, then full BLAKE2b) → `dups.json`.
Writes only to the output dir, tolerates files moving mid-scan. Run at idle priority:
`systemd-run -p Nice=19 -p IOSchedulingClass=idle python3 archive-inventory.py /path/to/archive /root/archive-inventory`
Used to plan a no-delete reorganisation: one layout (PC/GOG|DOS|Retail per game, Consoles/<platform>, Mac), CHD for disc images, hard links/block clones for true duplicates.
