# Self-hosted GitLab CE as a GitHub backup (+ CI runners)

GitHub stays the primary home for code; a LAN-only GitLab CE instance keeps a full copy and offers CI runners on homelab hardware.

**Layout (generic)**
- GitLab CE (Omnibus, official apt repo) in an **unprivileged LXC** (4 vCPU / 8 GB during install, trimmed for single-user use: puma single mode, sidekiq 10, built-in monitoring off), rootfs on fast local storage.
- Behind the reverse proxy (Nginx Proxy Manager): `git.lab.example.co.uk`, LAN/VPN access list, wildcard cert, websockets, no body-size limit. The container only accepts :80 from the proxy (Proxmox firewall); git-over-SSH goes straight to the container's own name (`git-ssh.lan`).
- **SSO via Authentik** (OIDC, `squidlab-gitlab.yaml` blueprint, bound to the admin user only). The client secret lives in a root-only file read by `gitlab.rb` at reconfigure time; nothing secret in config.
- Sign-ups, usage ping, version check, Gravatar and **Auto DevOps disabled** (otherwise every imported repo queues pipelines as soon as runners exist). CI is disabled on backup projects.
- Web IDE **single-origin fallback disabled** (assets only from the isolated extension-host domain).
- Backups: daily `gitlab-backup create` + `gitlab-ctl backup-etc` (keeps `gitlab-secrets.json`), picked up by the weekly PBS job.

**GitHub → GitLab backup** (`github-backup-sync.sh`, nightly cron): read-only fine-grained GitHub token; creates missing projects (CI off), fetches incrementally into a bare cache, pushes branches+tags. Nothing is ever deleted; a force-pushed branch's old tip is kept as tag `backup/<branch>/<date>`. Failures and token expiry (<30 d) go to ntfy.

**Runners** (`gitlab-runner-install.sh`): GitLab Runner (Docker executor, `debian:13` default image, concurrency 2) on two always-on unprivileged Docker LXCs, registered as instance runners with authentication tokens created via the API (piped over SSH, never printed).

Lessons: Debian 13 LXCs use socket-activated sshd (`ssh.socket`), so reloading `ssh.service` fails harmlessly; `gitlab-rails runner` runs as `git` (write temp files to `/tmp`); restoring a Docker host into an unprivileged CT needs `--ignore-unpack-errors` (device nodes like `backingFsBlockDev`) and dropped image layers.
