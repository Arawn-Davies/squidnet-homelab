#!/bin/bash
# Get a short-lived SQUIDNET SSH certificate from step-ca (ca.lab.example.co.uk) by logging in to Authentik.
#   ~/ssh-cert.sh          24 h certificate (default)
#   ~/ssh-cert.sh 7d       longest allowed (also 3d, 12h, 90m ...)
#   ~/ssh-cert.sh --show   show the current certificate
# Then: ssh root@<any SQUIDNET host>  (principals: root, arawn). Your old id_rsa key keeps working too.
set -euo pipefail
STEP=~/.local/bin/step; K=~/.ssh/id_squidnet
if [ "${1:-}" = "--show" ]; then ssh-keygen -Lf $K-cert.pub | grep -E "Key ID|Valid|Principals" -A2 | grep -v "^--"; exit 0; fi
DUR=${1:-24h}
case "$DUR" in *d) DUR=$(( ${DUR%d} * 24 ))h;; esac   # step only understands h/m/s
# Opens Authentik in your Windows browser; if it doesn't, copy the printed URL into the browser.
$STEP ssh certificate you@example.com $K --provisioner authentik --not-after "$DUR" \
  --no-password --insecure --force --add-user=false --no-agent 2>&1 | grep -vE "^✔ Provisioner" || true
chmod 600 $K
# One-time: use this key for SQUIDNET hosts (keeps id_rsa as the fallback)
touch ~/.ssh/config; chmod 600 ~/.ssh/config
grep -q "# SQUIDNET step-ca" ~/.ssh/config || cat >> ~/.ssh/config <<'CFG'

# SQUIDNET step-ca certificates (~/ssh-cert.sh)
Host 10.0.* *.lan *.lab.example.co.uk squid* sq*
    IdentityFile ~/.ssh/id_squidnet
    CertificateFile ~/.ssh/id_squidnet-cert.pub
    IdentityFile ~/.ssh/id_rsa
CFG
ssh-keygen -Lf $K-cert.pub | grep -E "Key ID|Valid:" | sed 's/^ */  /'
