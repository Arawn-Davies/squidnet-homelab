#!/bin/sh
# squidpatch probe: runs inside a node/CT/VM, prints package status sections. Read-only except `apt-get update`.
echo "##OS"; . /etc/os-release 2>/dev/null; echo "${ID:-unknown}|${VERSION_ID:-}|${PRETTY_NAME:-}|${VERSION_CODENAME:-}"
echo "##KERNEL"; uname -r
echo "##NEWEST_KERNEL"; ls /boot/vmlinuz-* 2>/dev/null | sed 's#.*/vmlinuz-##' | sort -V | tail -1
command -v pveversion >/dev/null 2>&1 && { echo "##PVE"; pveversion 2>/dev/null | head -1; }
command -v proxmox-backup-manager >/dev/null 2>&1 && { echo "##PBS"; proxmox-backup-manager version 2>/dev/null | head -1; }
if ! command -v apt-get >/dev/null 2>&1; then echo "##PM none"; echo "##END"; exit 0; fi
echo "##PM apt"
echo "##UPDATE"; LANG=C timeout 300 apt-get update -qq >/tmp/.squidpatch-upd 2>&1; echo "rc=$?"; grep -iE "^(W|E):" /tmp/.squidpatch-upd | head -3; rm -f /tmp/.squidpatch-upd
echo "##UPG"; LANG=C apt list --upgradable 2>/dev/null | grep -v '^Listing'
echo "##KEPT"; LANG=C apt-get -s -o Debug::NoLocking=1 full-upgrade 2>/dev/null | sed -n '/kept back/,/^[^ ]/p' | grep '^ ' | tr ' ' '\n' | grep -v '^$'
echo "##REBOOT"; if [ -f /var/run/reboot-required ]; then echo yes; cat /var/run/reboot-required.pkgs 2>/dev/null | sort -u | tr '\n' ' '; echo; else echo no; fi
echo "##AUTO"; apt-config dump 2>/dev/null | grep -E '^APT::Periodic::Unattended-Upgrade ' | grep -oE '"[0-9]+"' | tr -d '"'
echo "##END"
