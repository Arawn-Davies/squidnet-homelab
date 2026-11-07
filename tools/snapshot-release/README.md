# Releasing ZFS snapshots without losing anything

Snapshots taken before a big reorganisation (dedupe with hard links, merges, moves) keep the old blocks until they are destroyed.
These two tools prove that destroying them loses no file contents, and preserve anything that would be lost.

**Procedure**
1. Take a fresh reference snapshot (`zfs snapshot pool/ds@pre-release-<date>`). Every check compares old snapshot against this
   reference, so nothing races with live changes, and the reference protects anything changed afterwards.
2. Run the verifier, read-only, at low priority:
   `systemd-run --unit=snaprelease-verify -p Nice=19 -p IOSchedulingClass=best-effort -p IOSchedulingPriority=7 /usr/bin/python3 -I verify.py pre-release-<date> OLD1 OLD2 ...`
   For each old snapshot it does three independent checks:
   - `zfs diff OLD BASE` - every changed, removed and renamed entry;
   - a full walk of OLD, comparing object id, type, size and mtime with BASE - cross-checked against the diff
     (`walk_flagged_NOT_in_diff_unexplained` must be 0);
   - for every entry from either: a byte-for-byte search for its content in BASE - same path, rename target, hard-link keeper
     from your dedupe logs, moved directory, then any same-size file anywhere.
   Output in `OUT`: `unmatched.tsv` (no identical content anywhere), `meta.tsv` (original owner/mode/mtime of every candidate),
   `crosscheck-*.tsv`, `summary.json`, `progress.log`. `unmatched.tsv` is only complete once a snapshot's `DONE` line is logged.
3. `recover.py --dry-run`, then `recover.py`: copies every unmatched file (and symlink, and removed directory) out of its snapshot
   into the live dataset, never overwriting, keeping owner/mode/mtime, byte-verifying every copy.
4. `zfs destroy -nv` each old snapshot, then destroy them by exact name. Space is freed in the background (`zpool get freeing`).
5. Before destroying the reference itself, `zfs diff` it against the live dataset and preserve any change that is not intended.

Edit the constants at the top of each script (`DS`, `MP`, `OUT`, `LOGS`, `DEST`) for your pool and dedupe logs.

**Costs and caveats.** It reads every changed byte twice - on a ~2 M-file, multi-TB archive this took hours on spinning disks.
The same-size search is slow when many small files changed. ZFS largely ignores `ionice`. What is *not* preserved by design:
old directory names (listed in `unmatched.tsv`) and the original metadata of files that became hard links (listed in `meta.tsv`).
