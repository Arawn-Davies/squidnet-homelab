#!/bin/bash
# Per node: trust the SQUIDNET SSH user CA (step-ca on squidca) on this node and its running CTs. 2026-11-05
CA='ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBH38VHoHTEBPFUlAZbQEtET6/rut0q9Hip/OQJvXtMgWy0ChpCB8kfb/d3v9+Z8wanqVLSRgQ8ziQxqlBKQn6WE='
cat > /tmp/trust_ca_host.sh <<'HOST'
#!/bin/sh
CA="$1"; command -v sshd >/dev/null 2>&1 || [ -x /usr/sbin/sshd ] || { echo "no-sshd"; exit 0; }
SSHD=$(command -v sshd || echo /usr/sbin/sshd)
printf '%s\n' "$CA" > /etc/ssh/squidnet_user_ca.pub; chmod 644 /etc/ssh/squidnet_user_ca.pub
if grep -qE '^\s*Include\s+/etc/ssh/sshd_config\.d/\*\.conf' /etc/ssh/sshd_config && [ -d /etc/ssh/sshd_config.d ]; then
  printf '%s\n' "# SQUIDNET SSH CA (step-ca on squidca 10.0.0.55), 2026-11-05" "TrustedUserCAKeys /etc/ssh/squidnet_user_ca.pub" > /etc/ssh/sshd_config.d/10-squidnet-ca.conf; how=dropin
else
  grep -q '^TrustedUserCAKeys /etc/ssh/squidnet_user_ca.pub' /etc/ssh/sshd_config || { cp -n /etc/ssh/sshd_config /etc/ssh/sshd_config.bak-ca-2026-11-05; printf '\n%s\n' "TrustedUserCAKeys /etc/ssh/squidnet_user_ca.pub" >> /etc/ssh/sshd_config; }; how=main
fi
if $SSHD -t 2>/tmp/sshd-t.err; then
  (systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || rc-service sshd reload 2>/dev/null || /etc/init.d/sshd reload 2>/dev/null || /etc/init.d/ssh reload 2>/dev/null) >/dev/null
  eff=$($SSHD -T 2>/dev/null | grep -iE '^(trustedusercakeys|permitrootlogin|authorizedprincipalsfile) ' | awk '{print $1"="$2}' | tr '\n' ' ')
  echo "ok($how) $eff"
else
  rm -f /etc/ssh/sshd_config.d/10-squidnet-ca.conf; [ -f /etc/ssh/sshd_config.bak-ca-2026-11-05 ] && [ "$how" = main ] && cp /etc/ssh/sshd_config.bak-ca-2026-11-05 /etc/ssh/sshd_config
  echo "SKIPPED (sshd -t failed: $(head -1 /tmp/sshd-t.err)) - reverted"
fi
HOST
echo "$(hostname) (node): $(sh /tmp/trust_ca_host.sh "$CA")"
for id in $(pct list | awk 'NR>1 && $2=="running"{print $1}'); do
  pct push $id /tmp/trust_ca_host.sh /tmp/trust_ca_host.sh 2>/dev/null
  echo "  CT$id $(pct config $id | awk '/^hostname:/{print $2}'): $(pct exec $id -- sh /tmp/trust_ca_host.sh "$CA" </dev/null 2>&1 | tail -1)"
  pct exec $id -- rm -f /tmp/trust_ca_host.sh </dev/null
done
rm -f /tmp/trust_ca_host.sh
