#!/bin/bash
# NODE2: CT138 squidids (Suricata IDS on the vmbr9 mirror). 2026-11-05
set -euo pipefail
ID=138; IP=10.0.0.210; TPL=debian-13-standard_13.6-1_amd64.tar.zst
log(){ echo "[$(date +%T)] $*"; }
log "1. create CT$ID"
pct create $ID local:vztmpl/$TPL --hostname squidids --cores 2 --memory 3072 --swap 512 --rootfs cluster:16 \
  --net0 name=eth0,bridge=vmbr0,ip=$IP/16,gw=10.0.0.1,firewall=1 \
  --net1 name=eth1,bridge=vmbr9 \
  --nameserver 10.0.0.61 --searchdomain lan --unprivileged 1 --features nesting=1 --onboot 1 --tags "security;ids" \
  --description "Suricata IDS (detect-only). eth1 = vmbr9 mirror of NODE2 nic0 + flareon (private hosts + backup target excluded). Alerts-only logging; high severity -> ntfy squidnet-ids. Created 2026-11-05." >/dev/null
cat > /etc/pve/firewall/$ID.fw <<'FW'
[OPTIONS]
enable: 1
policy_in: ACCEPT
policy_out: ACCEPT

[RULES]
GROUP lan-mgmt # squidids: no inbound services
FW
pve-firewall compile 2>&1 | grep -i parse && { echo "fw parse error"; exit 1; } || true
pct start $ID; for i in $(seq 1 30); do pct exec $ID -- ping -c1 -W1 10.0.0.1 >/dev/null 2>&1 && break; sleep 2; done
log "2. install Suricata + ET Open"
pct exec $ID -- bash -c '
set -e; export DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
apt-get -qq update >/dev/null; apt-get -qq -y full-upgrade >/dev/null
apt-get -qq -y install suricata suricata-update jq curl unattended-upgrades >/dev/null
ip link set eth1 up promisc on
cat > /etc/suricata/squidnet.yaml <<Y
%YAML 1.1
---
vars:
  address-groups:
    HOME_NET: "[10.0.0.0/16,10.100.0.0/24,192.168.1.0/24]"
    EXTERNAL_NET: "!\$HOME_NET"
af-packet:
  - interface: eth1
    cluster-id: 99
    cluster-type: cluster_flow
    defrag: yes
    use-mmap: yes
    tpacket-v3: yes
default-rule-path: /var/lib/suricata/rules
rule-files:
  - suricata.rules
outputs:
  - eve-log:
      enabled: yes
      filetype: regular
      filename: eve.json
      types:
        - alert:
            payload: no
            payload-printable: no
            packet: no
            http-body: no
            metadata: no
            tagged-packets: no
        - stats:
            totals: yes
            threads: no
            deltas: no
  - fast:
      enabled: no
  - stats:
      enabled: yes
      filename: stats.log
      interval: 300
Y
grep -q "^include: /etc/suricata/squidnet.yaml" /etc/suricata/suricata.yaml || printf "\ninclude: /etc/suricata/squidnet.yaml\n" >> /etc/suricata/suricata.yaml
sed -i "s/^IFACE=.*/IFACE=eth1/; s/^LISTENMODE=.*/LISTENMODE=af-packet/" /etc/default/suricata 2>/dev/null || true
suricata-update -q --no-test 2>&1 | grep -iE "error|warn|Loaded|Writing" | tail -3 || true
echo "  rules: $(grep -c "^alert" /var/lib/suricata/rules/suricata.rules)"
suricata -T -c /etc/suricata/suricata.yaml -v 2>&1 | grep -iE "error|Configuration provided was successfully loaded|rules successfully loaded" | tail -3
suricata --dump-config -c /etc/suricata/suricata.yaml 2>/dev/null | grep -E "^outputs\.[0-9]+\.(eve-log\.types\.[0-9]+ |fast\.enabled|eve-log\.enabled)|^af-packet\.0\.interface|address-groups.HOME_NET" | head -8
' </dev/null
log "DONE (service started after the mirror is in place)"
