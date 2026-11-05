#!/bin/sh
# OpenWrt: feed CrowdSec (flareon LAPI) ban decisions into banIP's blocklist sets. Cron every 2 min. 2026-11-05
# Entries get the decision's remaining time as nft timeout; decisions removed early are deleted here.
LAPI=http://10.0.0.165:8080; KEY=$(cat /etc/crowdsec-banip.key 2>/dev/null) || exit 1
STATE=/tmp/crowdsec-banip.state; NEW=/tmp/crowdsec-banip.new.$$; RM=/tmp/crowdsec-banip.rm.$$
LOCK=/tmp/crowdsec-banip.lock
mkdir $LOCK 2>/dev/null || { [ -n "$(find $LOCK -mmin +5 2>/dev/null)" ] && rmdir $LOCK && mkdir $LOCK || exit 0; }
trap 'rmdir $LOCK 2>/dev/null; rm -f $NEW $RM' EXIT
J=$(curl -sf -m20 -H "X-Api-Key: $KEY" "$LAPI/v1/decisions/stream?startup=true&scopes=ip,range") || { logger -t crowdsec-banip "LAPI unreachable, keeping current entries"; exit 0; }
nft list set inet banIP blocklist.v4 >/dev/null 2>&1 || { logger -t crowdsec-banip "banIP set missing (banIP restarting?)"; exit 0; }
echo "$J" | jq -r '(.new // [])[] | select(.type=="ban") | "\(.value) \(.duration)"' | sort -u > $NEW
added=0
while read -r v d; do
  case "$d" in -*|"") continue;; esac
  d=$(echo "$d" | sed -E 's/\.[0-9]+s$/s/; s/^([0-9]+h)?([0-9]+m)?0s$/\1\2/'); [ -n "$d" ] || d=1m
  case "$v" in *:*) s=blocklist.v6;; *) s=blocklist.v4;; esac
  if ! nft get element inet banIP $s "{ $v }" >/dev/null 2>&1; then
    nft add element inet banIP $s "{ $v timeout $d }" 2>/dev/null && added=$((added+1))
  fi
done < $NEW
removed=0
if [ -f $STATE ]; then
  cut -d' ' -f1 $STATE | sort -u | while read -r v; do
    grep -q "^$v " $NEW && continue
    case "$v" in *:*) s=blocklist.v6;; *) s=blocklist.v4;; esac
    nft delete element inet banIP $s "{ $v }" 2>/dev/null && echo x
  done > $RM; removed=$(wc -l < $RM)
fi
mv $NEW $STATE
[ "$added$removed" != "00" ] && logger -t crowdsec-banip "active=$(wc -l < $STATE) added=$added removed=$removed"
exit 0
