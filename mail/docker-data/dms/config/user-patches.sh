#!/bin/bash
# mailhost: PGP/MIME encryption of incoming mail (see gpg/gpg-filter.py). Runs at every container start.
set -e
C=/tmp/docker-mailserver/gpg
install -d -o nobody -g nogroup -m 700 /var/lib/gpgfilter
for k in "$C"/keys/*.asc; do [ -f "$k" ] && su -s /bin/sh nobody -c "gpg --homedir /var/lib/gpgfilter --batch --quiet --import '$k'" 2>/dev/null || true; done
install -m 755 "$C/gpg-filter.py" /usr/local/bin/gpg-filter.py
grep -q '^gpgfilter ' /etc/postfix/master.cf || cat >> /etc/postfix/master.cf <<'M'
gpgfilter unix  -       n       n       -       10      pipe
  flags=Rq user=nobody null_sender= argv=/usr/local/bin/gpg-filter.py ${sender} ${recipient}
127.0.0.1:10026 inet n  -       n       -       10      smtpd
  -o content_filter=
  -o receive_override_options=no_unknown_recipient_checks,no_header_body_checks,no_milters,no_address_mappings
  -o mynetworks=127.0.0.0/8
  -o smtpd_client_restrictions=permit_mynetworks,reject
  -o smtpd_helo_restrictions=
  -o smtpd_sender_restrictions=
  -o smtpd_relay_restrictions=permit_mynetworks,reject
  -o smtpd_recipient_restrictions=permit_mynetworks,reject
  -o smtpd_data_restrictions=
  -o smtpd_end_of_data_restrictions=
  -o smtpd_sasl_auth_enable=no
  -o smtpd_tls_security_level=none
M
postconf -e 'content_filter = gpgfilter:dummy' 'gpgfilter_destination_recipient_limit = 1'
