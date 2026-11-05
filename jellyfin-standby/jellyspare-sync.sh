#!/bin/bash
# NODE5: refresh the Jellyfin standby (CT136 jellyspare, 10.0.0.170) from the primary (CT107 on NODE1).
# Runs at boot (jellyspare-sync.service) and nightly (jellyspare-sync.timer) while BLADE is on.
#  1. snapshot primary media (RAID/live) + CT107 rootfs on MICRO
#  2. incremental zfs send of the media into RAID/live-backup (read-only; also keeps the Jellyfin backup current)
#  3. copy CT107's /var/lib/jellyfin + /etc/jellyfin into CT136 (users, logins, watch state, libraries)
#  4. replace the writable media clone RAID/jellyspare-media with one of the new snapshot
#     (anything the standby wrote since the last sync is discarded on purpose)
#  5. software transcoding, same Jellyfin version as the primary, start + health check
#  6. keep only the newest standby-* snapshot (plus @backup-2026-11-04) on both sides
set -euo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
CT=136; SRC=RAID/live; DST=RAID/live-backup; CLONE=RAID/jellyspare-media; CLONEMP=/RAID/jellyspare-media
PRI_CT=107; PRI_FS=RAID/subvol-107-disk-0; MICRO=10.0.0.50
SSHO="-o BatchMode=yes -o ConnectTimeout=10 -o HostKeyAlias=NODE1 -o UserKnownHostsFile=/etc/pve/nodes/NODE1/ssh_known_hosts"
m(){ ssh $SSHO root@$MICRO "$@"; }
log(){ echo "[$(date '+%F %T')] $*"; }
exec 9>/run/jellyspare-sync.lock; flock -n 9 || { log "already running"; exit 0; }
exec > >(tee -a /var/log/jellyspare-sync.log) 2>&1

m true </dev/null || { log "NODE1 unreachable - standby keeps its last sync"; pct start $CT 2>/dev/null || true; exit 0; }
NEW=standby-$(date +%Y%m%d-%H%M)
log "1. snapshots on NODE1: $SRC@$NEW, $PRI_FS@$NEW"
m "zfs snapshot $SRC@$NEW && zfs snapshot $PRI_FS@$NEW" </dev/null
OK=0; trap '[ $OK = 1 ] || { log "!!! failed - removing $NEW snapshots on NODE1"; m "zfs destroy $PRI_FS@$NEW 2>/dev/null; zfs destroy $SRC@$NEW 2>/dev/null" </dev/null; pct start $CT 2>/dev/null || true; }' EXIT

mine=$(zfs list -H -t snapshot -o name -s createtxg $DST | sed 's/.*@//')
theirs=$(m "zfs list -H -t snapshot -o name -s createtxg $SRC" </dev/null | sed 's/.*@//')
common=""; for s in $mine; do echo "$theirs" | grep -qx "$s" && common=$s; done
[ -n "$common" ] || { log "!!! no common snapshot between $SRC and $DST - aborting"; m "zfs destroy $SRC@$NEW; zfs destroy $PRI_FS@$NEW" </dev/null; exit 1; }
log "2. media: incremental @$common -> @$NEW"
m "zfs send -L -i @$common $SRC@$NEW" </dev/null | zfs receive $DST   # -L: the first full send used large blocks
log "   received; $DST now at @$NEW ($(zfs get -H -o value referenced $DST))"

log "3. stop standby, copy CT$PRI_CT config"
pct shutdown $CT --timeout 60 2>/dev/null || pct stop $CT 2>/dev/null || true
R=$(zfs get -H -o value mountpoint RAID/subvol-$CT-disk-0)
for d in var/lib/jellyfin etc/jellyfin; do
  mkdir -p "$R/$d"
  rsync -aHAX --numeric-ids --delete -e "ssh $SSHO" "root@$MICRO:/$PRI_FS/.zfs/snapshot/$NEW/$d/" "$R/$d/"
done
m "zfs destroy $PRI_FS@$NEW" </dev/null
sed -i 's#<HardwareAccelerationType>[^<]*#<HardwareAccelerationType>none#' "$R/etc/jellyfin/encoding.xml"
log "   config copied ($(du -sh $R/var/lib/jellyfin | cut -f1)); transcoding set to software"

log "4. media clone -> @$NEW"
zfs list -H $CLONE >/dev/null 2>&1 && zfs destroy $CLONE
zfs clone -o mountpoint=$CLONEMP $DST@$NEW $CLONE

log "5. start standby, match Jellyfin version"
pct start $CT
for i in $(seq 1 30); do pct exec $CT -- true </dev/null 2>/dev/null && break; sleep 2; done
pv=$(m "pct exec $PRI_CT -- dpkg-query -W -f='\${Version}' jellyfin-server" </dev/null)
sv=$(pct exec $CT -- dpkg-query -W -f='${Version}' jellyfin-server </dev/null)
if [ -n "$pv" ] && [ "$pv" != "$sv" ]; then
  log "   primary $pv, standby $sv - aligning"
  pct exec $CT -- bash -c "systemctl stop jellyfin; apt-mark unhold jellyfin jellyfin-server jellyfin-web >/dev/null; apt-get -qq update; DEBIAN_FRONTEND=noninteractive apt-get -qq -y -o Dpkg::Options::=--force-confold install jellyfin=$pv jellyfin-server=$pv jellyfin-web=$pv >/dev/null; apt-mark hold jellyfin jellyfin-server jellyfin-web >/dev/null" </dev/null
fi
pct exec $CT -- systemctl restart jellyfin </dev/null
h=""; for i in $(seq 1 45); do h=$(pct exec $CT -- curl -s -m3 http://127.0.0.1:8096/health </dev/null 2>/dev/null || true); [ "$h" = Healthy ] && break; sleep 2; done
log "   standby health: ${h:-no answer}"

log "6. prune old standby snapshots"
for s in $(zfs list -H -t snapshot -o name $DST | sed 's/.*@//' | grep '^standby-' | grep -vx "$NEW"); do zfs destroy $DST@$s; done
m "for s in \$(zfs list -H -t snapshot -o name $SRC | sed 's/.*@//' | grep '^standby-' | grep -vx $NEW); do zfs destroy $SRC@\$s; done" </dev/null
OK=1; log "DONE (standby = primary as of $NEW)"
