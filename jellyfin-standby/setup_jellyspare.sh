#!/bin/bash
# NODE5, one-time: create CT136 jellyspare (Jellyfin standby, 10.0.0.170) + sync units. 2026-11-05
set -euo pipefail
ID=136; IP=10.0.0.170; V=12.4+ubu2404; FF=8.1.3-2-noble
log(){ echo "[$(date +%T)] $*"; }

log "1. uid/gid passthrough (jellyfin 107, media 1000) like CT107"
grep -qx "root:107:1" /etc/subuid || echo "root:107:1" >> /etc/subuid
for f in /etc/subuid /etc/subgid; do grep -qx "root:1000:1" $f || echo "root:1000:1" >> $f; done

log "2. template + initial writable media clone"
pveam update >/dev/null 2>&1 || true
TPL=$(pveam available --section system | awk '/ubuntu-24.04-standard/{print $2}' | sort -V | tail -1)
[ -f /var/lib/vz/template/cache/$TPL ] || pveam download local $TPL >/dev/null
zfs list -H RAID/jellyspare-media >/dev/null 2>&1 || zfs clone -o mountpoint=/RAID/jellyspare-media RAID/live-backup@backup-2026-11-04 RAID/jellyspare-media
ls /RAID/jellyspare-media/squidjelly >/dev/null

log "3. create CT$ID ($TPL)"
pct create $ID local:vztmpl/$TPL --hostname jellyspare --cores 6 --memory 6144 --swap 1024 --rootfs cluster:16 \
  --net0 name=eth0,bridge=vmbr0,ip=$IP/16,gw=10.0.0.1,firewall=1 --nameserver 10.0.0.61 --searchdomain lan \
  --unprivileged 1 --features nesting=1 --onboot 1 --tags "media;standby" \
  --mp0 /RAID/jellyspare-media/squidjelly,mp=/mnt/Media \
  --description "Jellyfin STANDBY for CT107 squidjelly. Refreshed from NODE1 at every BLADE boot + 04:15 (jellyspare-sync). Software transcoding. Writes are discarded at the next sync. Created 2026-11-05." >/dev/null
cat >> /etc/pve/lxc/$ID.conf <<'MAP'
lxc.idmap: u 0 100000 107
lxc.idmap: u 107 107 1
lxc.idmap: u 108 100108 892
lxc.idmap: u 1000 1000 1
lxc.idmap: u 1001 101001 64535
lxc.idmap: g 0 100000 1000
lxc.idmap: g 1000 1000 1
lxc.idmap: g 1001 101001 64535
MAP
cat > /etc/pve/firewall/$ID.fw <<'FW'
[OPTIONS]
enable: 1
policy_in: ACCEPT
policy_out: ACCEPT

[RULES]
IN ACCEPT -source +lan -p tcp -dport 8096 # Jellyfin standby: LAN only (incl. flareon 10.0.0.165 and NPM 10.0.0.95)
IN DROP -p tcp -dport 8096
IN DROP -p tcp -dport 8920
IN DROP -p udp -dport 1900
IN DROP -p udp -dport 7359
GROUP lan-mgmt
FW
pve-firewall compile 2>&1 | grep -i "parse" && { echo "firewall parse error"; exit 1; } || true

log "4. start + install Jellyfin $V (same as primary, held)"
pct start $ID
for i in $(seq 1 30); do pct exec $ID -- ping -c1 -W1 10.0.0.1 >/dev/null 2>&1 && break; sleep 2; done
pct exec $ID -- bash -c "
set -e; export DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
getent group 110 >/dev/null && [ \"\$(getent group 110 | cut -d: -f1)\" != jellyfin ] && { echo 'gid 110 taken'; exit 1; }
getent group jellyfin >/dev/null || groupadd -g 110 jellyfin
getent group media >/dev/null || groupadd -g 1000 media
id jellyfin >/dev/null 2>&1 || useradd -r -u 107 -g 110 -G media -d /var/lib/jellyfin -s /usr/sbin/nologin jellyfin
apt-get -qq update >/dev/null && apt-get -qq -y full-upgrade >/dev/null && apt-get -qq -y install curl gnupg ca-certificates >/dev/null
install -d -m 755 /etc/apt/keyrings
curl -fsSL https://repo.jellyfin.org/jellyfin_team.gpg.key | gpg --dearmor --yes -o /etc/apt/keyrings/jellyfin.gpg
printf 'Types: deb\nURIs: https://repo.jellyfin.org/ubuntu\nSuites: noble\nComponents: main\nSigned-By: /etc/apt/keyrings/jellyfin.gpg\n' > /etc/apt/sources.list.d/jellyfin.sources
apt-get -qq update >/dev/null
apt-get -qq -y -o Dpkg::Options::=--force-confold install jellyfin=$V jellyfin-server=$V jellyfin-web=$V jellyfin-ffmpeg8=$FF >/dev/null
apt-mark hold jellyfin jellyfin-server jellyfin-web jellyfin-ffmpeg8 >/dev/null
systemctl stop jellyfin
echo \"  installed: \$(dpkg-query -W -f='\${Version}' jellyfin-server), user: \$(id jellyfin)\"
gpg --show-keys --with-colons /etc/apt/keyrings/jellyfin.gpg | awk -F: '/^fpr/{print \"  repo key: \"\$10; exit}'
" </dev/null

log "5. sync units"
install -m 755 /root/jellyspare-sync.sh /usr/local/sbin/jellyspare-sync.sh
cat > /etc/systemd/system/jellyspare-sync.service <<'U'
[Unit]
Description=Refresh Jellyfin standby CT136 from the primary (CT107 on NODE1)
After=network-online.target pve-guests.service pve-cluster.service
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/jellyspare-sync.sh
TimeoutStartSec=6h

[Install]
WantedBy=multi-user.target
U
cat > /etc/systemd/system/jellyspare-sync.timer <<'U'
[Unit]
Description=Nightly Jellyfin standby refresh (only while NODE5 is on)
[Timer]
OnCalendar=*-*-* 04:15
[Install]
WantedBy=timers.target
U
systemctl daemon-reload; systemctl enable jellyspare-sync.service jellyspare-sync.timer >/dev/null 2>&1
log "DONE - run the first sync: systemctl start jellyspare-sync"
