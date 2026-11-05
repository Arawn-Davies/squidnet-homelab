#!/bin/bash
# SQUIDNET WireGuard peers on the OpenWrt router (wg0, 10.100.0.0/24).
#   ~/wg-peer.sh <name>            add a device; prints its config + QR code HERE only
#   ~/wg-peer.sh --list            list devices
#   ~/wg-peer.sh --remove <name>   revoke a device
# The device's private key is generated on the router in RAM, shown once, then deleted.
# Clients reach 10.0.0.0/16 (never the private media host 10.0.0.175) and use the router for DNS.
set -euo pipefail
R=root@10.0.0.1
ENDPOINT=${WG_ENDPOINT:-vpn.example.co.uk}:51820

case "${1:-}" in
  ""|-h|--help) sed -n '2,7p' "$0"; exit 0;;
  --list)
    ssh -n $R 'for s in $(uci show network | grep -oE "^network\.wgpeer_[a-z0-9_]+=wireguard_wg0" | cut -d. -f2 | cut -d= -f1); do
      echo "$(uci get network.$s.description)  $(uci get network.$s.allowed_ips)"; done
      echo; wg show wg0 latest-handshakes | while read k t; do n=$(uci show network | grep -F "$k" | cut -d. -f2); [ "$t" = 0 ] && w=never || w=$(date -d @$t "+%F %T"); echo "last handshake: $(uci -q get network.$n.description) $w"; done'
    exit 0;;
  --remove)
    n=$(echo "${2:?name}" | tr 'A-Z-' 'a-z_' | tr -cd 'a-z0-9_')
    ssh -n $R "uci -q delete network.wgpeer_$n && uci commit network && ifup wg0 && echo 'removed $2' || echo 'no such device: $2'"
    exit 0;;
esac

NAME="$1"; n=$(echo "$NAME" | tr 'A-Z-' 'a-z_' | tr -cd 'a-z0-9_'); [ -n "$n" ] || { echo "bad name"; exit 1; }
OUT=$(ssh -n $R "set -e
  uci -q get network.wgpeer_$n >/dev/null && { echo 'EXISTS'; exit 0; }
  used=\$(uci show network | grep -oE \"allowed_ips='10\.100\.0\.[0-9]+\" | cut -d. -f4)
  ip=''; for o in \$(seq 5 5 250); do echo \"\$used\" | grep -qx \"\$o\" || { ip=\$o; break; }; done
  [ -n \"\$ip\" ] || { echo FULL; exit 0; }
  d=\$(mktemp -d /tmp/wgp.XXXXXX); umask 077
  wg genkey > \$d/k; wg pubkey < \$d/k > \$d/p; wg genpsk > \$d/s
  uci batch <<UCI
set network.wgpeer_$n=wireguard_wg0
set network.wgpeer_$n.description='$NAME'
set network.wgpeer_$n.public_key='\$(cat \$d/p)'
set network.wgpeer_$n.preshared_key='\$(cat \$d/s)'
add_list network.wgpeer_$n.allowed_ips='10.100.0.\$ip/32'
set network.wgpeer_$n.persistent_keepalive='25'
UCI
  uci commit network; ifup wg0
  cat <<CONF > \$d/c
[Interface]
# $NAME (SQUIDNET)
PrivateKey = \$(cat \$d/k)
Address = 10.100.0.\$ip/32
DNS = 10.0.0.1, lab.example.co.uk, lan
MTU = 1380

[Peer]
PublicKey = \$(cat /etc/wireguard/server.pub)
PresharedKey = \$(cat \$d/s)
Endpoint = $ENDPOINT
AllowedIPs = 10.0.0.0/16, 10.100.0.0/24
PersistentKeepalive = 25
CONF
  echo '===CONF==='; cat \$d/c; echo '===QR==='; qrencode -t ansiutf8 < \$d/c
  rm -rf \$d")
case "$OUT" in EXISTS) echo "A device called '$NAME' already exists (use --remove first)"; exit 1;; FULL) echo "no free addresses"; exit 1;; esac
CONF=$(sed -n '/===CONF===/,/===QR===/p' <<<"$OUT" | sed '1d;$d')
F=~/wg-$n.conf; (umask 077; printf '%s\n' "$CONF" > "$F")
sed -n '/===QR===/,$p' <<<"$OUT" | sed '1d'
echo "Phone: scan the QR code with the WireGuard app (+ → Scan from QR code)."
echo "PC: import $F into the WireGuard app, then delete the file:  rm $F"
