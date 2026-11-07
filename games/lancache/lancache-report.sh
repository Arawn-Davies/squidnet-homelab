#!/bin/bash
# Read-only LANCache report: one line per Steam depot (requests, MB served, HIT/MISS, last request), plus totals.
# Run where the cache's logs are mounted (the LANCache container host). Usage: lancache-report.sh [access.log]
# Feed the depot column to steam-depot-names.py to turn depot IDs into game names.
L=${1:-/data/lancache/logs/access.log}
CACHE=${LANCACHE_DATA:-/data/lancache/data}
T=$(mktemp); trap 'rm -f "$T"' EXIT
grep -v lancache-heartbeat "$L" | grep -E '^\[steam\]' > "$T" || true
printf 'depot\treq\tMB\thits\tmisses\tlast\n'
grep -oE '/depot/[0-9]+/' "$T" | grep -oE '[0-9]+' | sort -u | while read -r id; do
  grep "/depot/$id/" "$T" | awk -F'"' -v id="$id" '
    { split($3, b, " "); s += b[2]; n++; st[$(NF-5)]++
      if (match($0, /\[[0-9]{2}\/[A-Za-z]{3}\/[0-9]{4}:[0-9:]{8}/)) last = substr($0, RSTART+1, RLENGTH-1) }
    END { printf "%s\t%d\t%.1f\t%d\t%d\t%s\n", id, n, s/1e6, st["HIT"], st["MISS"], last }'
done
echo "clients: $(awk '{print $2}' "$T" | sort -u | tr '\n' ' ')"
echo "total served: $(awk -F'"' '{split($3, b, " "); s += b[2]} END {printf "%.1f GB", s/1e9}' "$T")"
[ -d "$CACHE" ] && echo "cache on disk: $(du -sh "$CACHE" | cut -f1)"
echo "last real request: $(sed -n '$p' "$T" | grep -oE '[0-9]{2}/[A-Za-z]{3}/[0-9]{4}:[0-9:]{8}')"
