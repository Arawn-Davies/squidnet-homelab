#!/usr/bin/env python3
"""Postfix content filter (mailhost): encrypt incoming mail to recipients that have a public key, as PGP/MIME (RFC 3156).
Called once per recipient (gpgfilter_destination_recipient_limit=1): gpg-filter.py <sender> <recipient>
Re-injects on 127.0.0.1:10026 (a no-filter smtpd). Messages already encrypted, or to recipients without a key, pass unchanged.
On encryption failure the original is delivered with 'X-Squidnet-Encryption: failed' (never lose mail). Exit 75 = tempfail."""
import email, email.policy, os, smtplib, subprocess, sys, syslog, uuid
GNUPGHOME = "/var/lib/gpgfilter"
syslog.openlog("gpg-filter", syslog.LOG_PID, syslog.LOG_MAIL)
def log(m): syslog.syslog(m)
def has_key(rcpt):
    r = subprocess.run(["gpg", "--homedir", GNUPGHOME, "--batch", "--list-keys", "--with-colons", f"<{rcpt}>"], capture_output=True)
    return r.returncode == 0 and b"\npub:" in b"\n" + r.stdout
def encrypt(raw, rcpt):
    msg = email.message_from_bytes(raw, policy=email.policy.SMTP)
    ctype = msg.get_content_type()
    if ctype == "multipart/encrypted" or b"-----BEGIN PGP MESSAGE-----" in raw:
        return raw, "already-encrypted"
    hdr, sep, body = raw.partition(b"\r\n\r\n") if b"\r\n\r\n" in raw else raw.partition(b"\n\n")
    nl = b"\r\n" if b"\r\n" in hdr else b"\n"
    lines = hdr.split(nl); outer, inner, cur = [], [], None
    for ln in lines:
        if ln[:1] in (b" ", b"\t") and cur is not None: cur.append(ln); continue
        cur = inner if ln.lower().startswith((b"content-", b"mime-version")) else outer
        cur.append(ln)
    inner = [l for l in inner if not l.lower().startswith(b"mime-version")] or [b"Content-Type: text/plain; charset=utf-8"]
    plain = nl.join(inner) + nl + nl + body
    g = subprocess.run(["gpg", "--homedir", GNUPGHOME, "--batch", "--armor", "--trust-model", "always", "--encrypt", "-r", f"<{rcpt}>"],
                       input=plain, capture_output=True, timeout=60)
    if g.returncode != 0: raise RuntimeError(g.stderr.decode(errors="replace")[:300])
    b = ("squidnet-" + uuid.uuid4().hex).encode()
    new = nl.join(outer + [b"MIME-Version: 1.0", b'Content-Type: multipart/encrypted; protocol="application/pgp-encrypted"; boundary="' + b + b'"',
                           b"X-Squidnet-Encryption: pgp"]) + nl + nl
    new += b"This is an OpenPGP/MIME encrypted message (RFC 3156)." + nl + nl
    new += b"--" + b + nl + b"Content-Type: application/pgp-encrypted" + nl + b"Content-Description: PGP/MIME version identification" + nl + nl + b"Version: 1" + nl + nl
    new += b"--" + b + nl + b'Content-Type: application/octet-stream; name="encrypted.asc"' + nl + b"Content-Description: OpenPGP encrypted message" + nl
    new += b'Content-Disposition: inline; filename="encrypted.asc"' + nl + nl + g.stdout.replace(b"\n", nl) + nl + b"--" + b + b"--" + nl
    return new, "encrypted"
def main():
    sender, rcpts = sys.argv[1], sys.argv[2:]
    raw = sys.stdin.buffer.read(); out, state = raw, "no-key"
    if len(rcpts) == 1 and has_key(rcpts[0]):
        try: out, state = encrypt(raw, rcpts[0])
        except Exception as e:
            state = "failed"; log(f"encryption FAILED for {rcpts[0]}: {e}")
            out = b"X-Squidnet-Encryption: failed\r\n" + raw
    try:
        with smtplib.SMTP("127.0.0.1", 10026, timeout=60) as s:
            s.sendmail(sender or "", rcpts, out)
    except Exception as e:
        log(f"reinject failed ({state}) for {rcpts}: {e}"); sys.exit(75)
    log(f"{state}: {sender} -> {','.join(rcpts)} ({len(raw)} -> {len(out)} bytes)")
if __name__ == "__main__": main()
