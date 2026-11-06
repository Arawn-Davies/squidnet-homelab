# Internal mail: docker-mailserver (Postfix + Dovecot) + Roundcube with Authentik SSO

Fully FOSS (MIT / GPL, no paid tiers). Internal-only: the lab domain's MX exists only on the LAN DNS.

- **IMAP only** (POP3 off): mail stays on the server, synced to the desktop client, phone (VPN) and webmail; backed up with the container.
- **Internal-only, enforced three ways**: `smtpd_relay_restrictions = reject_unauth_destination` (also on 465/587 via `postfix-master.cf`, so even logged-in users can't send outside), `default_transport`/`relay_transport` = error, and the guest firewall drops outbound 25/465/587. `SPOOF_PROTECTION=1`: a login can only send as itself (services use a dedicated `alerts@` account).
- **TLS**: the reverse proxy's wildcard certificate, copied in nightly (`SSL_TYPE=manual`).
- **Webmail SSO**: Roundcube (`oauth_provider = generic`) logs in via Authentik and authenticates to IMAP/SMTP with the token (XOAUTH2/OAUTHBEARER). Dovecot (`ENABLE_OAUTH2=1`) validates the token against Authentik's **userinfo** endpoint and uses the `email` claim as the mailbox - so the Authentik app emits the internal mailbox address from a user attribute (set it by merging into the user, **not** from a blueprint: blueprints replace the whole attributes dict on every re-apply). Password logins keep working for desktop/phone clients.
- Not needed internally and switched off: spam/AV filtering, SPF/DMARC checks, DNSBLs, update check.
