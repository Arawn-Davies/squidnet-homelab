#!/bin/bash
# stdin: line1 = runner auth token (glrt-...). arg1 = runner name
set -euo pipefail
read -r TOKEN; NAME="$1"
export DEBIAN_FRONTEND=noninteractive
if ! command -v gitlab-runner >/dev/null; then
  apt-get update -q >/dev/null; apt-get install -y -q curl ca-certificates gnupg >/dev/null
  curl -fsSL https://packages.gitlab.com/runner/gitlab-runner/gpgkey | gpg --dearmor -o /usr/share/keyrings/gitlab-runner.gpg
  printf 'Types: deb\nURIs: https://packages.gitlab.com/runner/gitlab-runner/debian\nSuites: trixie\nComponents: main\nSigned-By: /usr/share/keyrings/gitlab-runner.gpg\n' > /etc/apt/sources.list.d/gitlab-runner.sources
  apt-get update -q >/dev/null; apt-get install -y -q gitlab-runner >/dev/null
fi
usermod -aG docker gitlab-runner 2>/dev/null || true
gitlab-runner list 2>&1 | grep -q "$NAME" && gitlab-runner unregister --name "$NAME" >/dev/null 2>&1 || true
gitlab-runner register --non-interactive --url https://git.lab.example.co.uk --token "$TOKEN" --name "$NAME" \
  --executor docker --docker-image debian:13 --docker-pull-policy if-not-present >/dev/null 2>&1
sed -i 's/^concurrent = .*/concurrent = 2/' /etc/gitlab-runner/config.toml
systemctl enable --now gitlab-runner >/dev/null 2>&1; systemctl restart gitlab-runner
sleep 3; echo "$NAME: $(gitlab-runner --version | head -1) | service $(systemctl is-active gitlab-runner) | verify: $(gitlab-runner verify 2>&1 | grep -oE 'is (alive|valid|removed)[^"]*' | head -1)"
