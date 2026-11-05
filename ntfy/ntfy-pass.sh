#!/bin/bash
# Create (or change the password of) your ntfy login on squidntfy (CT137). Typed here, hidden, sent over SSH stdin.
# Then in the ntfy app: Settings > Manage users > add https://ntfy.example.co.uk with user "arawn",
# and subscribe to topics:  squidnet-alerts  (Grafana)   squidnet-ids  (Suricata)
set -euo pipefail
read -rsp "New ntfy password for user 'arawn': " P; echo
read -rsp "Again: " P2; echo
[ "$P" = "$P2" ] || { echo "passwords differ"; exit 1; }
[ ${#P} -ge 12 ] || { echo "use at least 12 characters"; exit 1; }
printf '%s\n' "$P" | ssh root@10.0.0.50 "ssh -o BatchMode=yes -o HostKeyAlias=NODE2 -o UserKnownHostsFile=/etc/pve/nodes/NODE2/ssh_known_hosts root@10.0.0.40 'pct exec 137 -- bash -c \"read -r P; if ntfy user list 2>&1 | grep -q \\\"^user arawn\\\"; then NTFY_PASSWORD=\\\"\\\$P\\\" ntfy user change-pass arawn; else NTFY_PASSWORD=\\\"\\\$P\\\" ntfy user add --role=admin arawn; fi\"'" 2>&1 | grep -vi password || true
unset P P2
echo "Done. Log in at https://ntfy.example.co.uk (once the Cloudflare public hostname exists) as 'arawn'."
