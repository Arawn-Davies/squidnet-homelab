#!/bin/bash
# Point vpn.example.co.uk at the home IP and keep it updated (ddns-scripts on the OpenWrt router).
# Before running, in the Cloudflare dashboard:
#   1. DNS > Records for example.co.uk: add an A record "vpn", any IP (e.g. 192.0.2.1), Proxy status OFF (grey cloud, "DNS only").
#   2. My Profile > API Tokens > Create Token > "Edit zone DNS" template, Zone Resources = example.co.uk only.
# The token is typed here (hidden), sent over SSH stdin to the router, and never shown or logged.
set -euo pipefail
read -rsp "Cloudflare API token (Edit zone DNS, example.co.uk only): " T; echo
[ ${#T} -ge 30 ] || { echo "that doesn't look like a token"; exit 1; }
printf '%s\n' "$T" | ssh root@10.0.0.1 'read -r T
for s in myddns_ipv4 myddns_ipv6; do uci -q set ddns.$s.enabled=0; done
uci -q delete ddns.vpn || true
uci batch <<UCI
set ddns.vpn=service
set ddns.vpn.enabled=1
set ddns.vpn.service_name=cloudflare.com-v4
set ddns.vpn.lookup_host=vpn.example.co.uk
set ddns.vpn.domain=vpn@example.co.uk
set ddns.vpn.username=Bearer
set ddns.vpn.password=$T
set ddns.vpn.use_https=1
set ddns.vpn.cacert=/etc/ssl/certs
set ddns.vpn.use_ipv6=0
set ddns.vpn.ip_source=web
set ddns.vpn.ip_url=https://cloudflare.com/cdn-cgi/trace
set ddns.vpn.interface=wan
set ddns.vpn.check_interval=5
set ddns.vpn.check_unit=minutes
set ddns.vpn.force_interval=24
set ddns.vpn.force_unit=hours
UCI
uci commit ddns; chmod 600 /etc/config/ddns
/etc/init.d/ddns enable; /etc/init.d/ddns restart; sleep 25
grep -hiE "update successful|registered ip|detected local ip|error|failed|forced update" /var/log/ddns/vpn.log 2>/dev/null | tail -6 | sed -E "s/[A-Za-z0-9_-]{30,}/<hidden>/g"'
unset T
echo; echo "Check from outside the LAN: nslookup vpn.example.co.uk 1.1.1.1"
