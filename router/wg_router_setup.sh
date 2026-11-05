#!/bin/sh
# OpenWrt 10.0.0.1: WireGuard server wg0 (10.100.0.0/24, UDP 51820). Routed, no NAT. 2026-11-05
set -e
for f in network firewall dhcp; do [ -f /etc/config/$f.bak-wg-2026-11-05 ] || cp /etc/config/$f /etc/config/$f.bak-wg-2026-11-05; done
echo "1. packages"
apk update >/dev/null 2>&1
apk add wireguard-tools kmod-wireguard luci-proto-wireguard qrencode 2>&1 | grep -E "^OK|ERROR|Installing" | sed 's/^/   /'
echo "2. server key (stays on the router, never printed)"
mkdir -p /etc/wireguard; chmod 700 /etc/wireguard
[ -f /etc/wireguard/server.key ] || (umask 077; wg genkey > /etc/wireguard/server.key)
wg pubkey < /etc/wireguard/server.key > /etc/wireguard/server.pub
echo "3. interface wg0"
uci -q delete network.wg0 || true
uci batch <<UCI
set network.wg0=interface
set network.wg0.proto='wireguard'
set network.wg0.private_key='$(cat /etc/wireguard/server.key)'
set network.wg0.listen_port='51820'
add_list network.wg0.addresses='10.100.0.1/24'
set network.wg0.mtu='1380'
UCI
echo "4. firewall zone vpn"
for s in $(uci show firewall | grep -E "\.name='(vpn|Allow-WireGuard-Inbound|VPN-DNS|VPN-ICMP|VPN-never-private-host)'" | cut -d. -f2 | sort -ru); do uci delete firewall.$s; done
for s in $(uci show firewall | grep -E "forwarding.*\.src='vpn'" | cut -d. -f2 | sort -ru); do uci delete firewall.$s; done
uci batch <<'UCI'
add firewall rule
set firewall.@rule[-1].name='VPN-never-private-host'
set firewall.@rule[-1].src='vpn'
set firewall.@rule[-1].dest='lan'
set firewall.@rule[-1].dest_ip='10.0.0.175'
set firewall.@rule[-1].proto='all'
set firewall.@rule[-1].target='REJECT'
add firewall zone
set firewall.@zone[-1].name='vpn'
add_list firewall.@zone[-1].network='wg0'
set firewall.@zone[-1].input='REJECT'
set firewall.@zone[-1].output='ACCEPT'
set firewall.@zone[-1].forward='REJECT'
add firewall forwarding
set firewall.@forwarding[-1].src='vpn'
set firewall.@forwarding[-1].dest='lan'
add firewall rule
set firewall.@rule[-1].name='Allow-WireGuard-Inbound'
set firewall.@rule[-1].src='wan'
set firewall.@rule[-1].proto='udp'
set firewall.@rule[-1].dest_port='51820'
set firewall.@rule[-1].target='ACCEPT'
add firewall rule
set firewall.@rule[-1].name='VPN-DNS'
set firewall.@rule[-1].src='vpn'
add_list firewall.@rule[-1].proto='tcp'
add_list firewall.@rule[-1].proto='udp'
set firewall.@rule[-1].dest_port='53'
set firewall.@rule[-1].target='ACCEPT'
add firewall rule
set firewall.@rule[-1].name='VPN-ICMP'
set firewall.@rule[-1].src='vpn'
set firewall.@rule[-1].proto='icmp'
set firewall.@rule[-1].target='ACCEPT'
UCI
uci commit network; uci commit firewall
echo "5. apply"
ifup wg0; sleep 3; /etc/init.d/firewall reload >/dev/null 2>&1
echo "6. verify"
wg show wg0 | grep -E "interface|listening port" | sed 's/^/   /'
ip -4 addr show wg0 | grep inet | sed 's/^/   /'
nft list chain inet fw4 forward_vpn 2>/dev/null | grep -E "10.0.0.175|jump|reject" | sed 's/^ */   nft: /'
nft list chain inet fw4 input_wan | grep -E "51820" | sed 's/^ */   nft: /'
echo "   server public key: $(cat /etc/wireguard/server.pub)"
