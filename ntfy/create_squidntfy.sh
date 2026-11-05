#!/bin/bash
# NODE2: CT137 squidntfy (self-hosted ntfy push notifications). 2026-11-05
set -euo pipefail
ID=137; IP=10.0.0.205; TPL=debian-13-standard_13.6-1_amd64.tar.zst
log(){ echo "[$(date +%T)] $*"; }
log "1. create CT$ID"
pct create $ID local:vztmpl/$TPL --hostname squidntfy --cores 1 --memory 512 --swap 256 --rootfs cluster:4 \
  --net0 name=eth0,bridge=vmbr0,ip=$IP/16,gw=10.0.0.1,firewall=1 --nameserver 10.0.0.61 --searchdomain lan \
  --unprivileged 1 --features nesting=1 --onboot 1 --tags "notify" \
  --description "ntfy push notifications (Grafana + Suricata alerts). Public as ntfy.example.co.uk via flareon tunnel; deny-all, login required. Created 2026-11-05." >/dev/null
cat > /etc/pve/firewall/$ID.fw <<'FW'
[OPTIONS]
enable: 1
policy_in: ACCEPT
policy_out: ACCEPT

[RULES]
IN ACCEPT -source +lan -p tcp -dport 2586 # ntfy: LAN only (flareon 10.0.0.165 publishes it; Grafana/Suricata post locally)
IN DROP -p tcp -dport 2586
GROUP lan-mgmt
FW
pve-firewall compile 2>&1 | grep -i parse && { echo "fw parse error"; exit 1; } || true
pct start $ID; for i in $(seq 1 30); do pct exec $ID -- ping -c1 -W1 10.0.0.1 >/dev/null 2>&1 && break; sleep 2; done
log "2. install ntfy (official repo, key fingerprint checked)"
pct exec $ID -- bash -c '
set -e; export DEBIAN_FRONTEND=noninteractive LANG=C.UTF-8
apt-get -qq update >/dev/null; apt-get -qq -y full-upgrade >/dev/null; apt-get -qq -y install curl gnupg ca-certificates unattended-upgrades >/dev/null
install -d -m 755 /etc/apt/keyrings
curl -fsSL -o /etc/apt/keyrings/ntfy.gpg https://archive.ntfy.sh/apt/keyring.gpg
fp=$(gpg --show-keys --with-colons /etc/apt/keyrings/ntfy.gpg 2>/dev/null | awk -F: "/^fpr/{print \$10; exit}")
[ "$fp" = 55BA774A6F5EE67431E4B6B7CFDB962D4F1EC4AF ] || { echo "KEY FINGERPRINT MISMATCH: $fp"; exit 1; }
echo "  key ok: $fp"
echo "deb [arch=amd64 signed-by=/etc/apt/keyrings/ntfy.gpg] https://archive.ntfy.sh/apt stable main" > /etc/apt/sources.list.d/ntfy.list
apt-get -qq update >/dev/null; apt-get -qq -y install ntfy >/dev/null
cat > /etc/ntfy/server.yml <<YML
# squidntfy (CT137) - 2026-11-05
base-url: "https://ntfy.example.co.uk"
listen-http: ":2586"
behind-proxy: true
proxy-forwarded-header: "X-Forwarded-For"
cache-file: "/var/cache/ntfy/cache.db"
cache-duration: "72h"
auth-file: "/var/lib/ntfy/user.db"
auth-default-access: "deny-all"
enable-signup: false
enable-login: true
enable-reservations: false
log-level: "info"
YML
install -d -o ntfy -g ntfy /var/cache/ntfy /var/lib/ntfy
systemctl enable ntfy >/dev/null 2>&1; systemctl restart ntfy; sleep 2
echo "  ntfy: $(ntfy --help 2>&1 | grep -m1 -oE "ntfy [0-9.]+" || ntfy serve --help 2>&1 | head -0) $(systemctl is-active ntfy)"
ntfy version 2>/dev/null | head -1 || true
NTFY_PASSWORD=$(head -c 32 /dev/urandom | base64 | tr -dc A-Za-z0-9 | head -c 32) ntfy user add --role=user alerts >/dev/null 2>&1 || true
ntfy access alerts "squidnet-*" write-only >/dev/null
umask 077; ntfy token add --label "grafana+suricata publisher" alerts 2>/dev/null | grep -oE "tk_[A-Za-z0-9]+" > /root/alerts.token
echo "  alerts user: write-only on squidnet-*, token saved root-only ($(wc -c < /root/alerts.token) bytes)"
echo "  anonymous publish (expect 403): $(curl -s -o /dev/null -w %{http_code} -d test http://127.0.0.1:2586/squidnet-alerts)"
echo "  token publish (expect 200): $(curl -s -o /dev/null -w %{http_code} -H "Authorization: Bearer $(cat /root/alerts.token)" -H "Title: squidntfy online" -d "ntfy installed on CT137 (test message)" http://127.0.0.1:2586/squidnet-alerts)"
echo "  token read (expect 403, write-only): $(curl -s -o /dev/null -w %{http_code} -H "Authorization: Bearer $(cat /root/alerts.token)" "http://127.0.0.1:2586/squidnet-alerts/json?poll=1")"
' </dev/null
log "DONE"
