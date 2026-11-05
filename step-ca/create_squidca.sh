#!/bin/bash
# On NODE2. VM 135 squidca (step-ca SSH CA). 2026-11-05
set -euo pipefail
ID=135; D=/var/lib/vz/template/iso; IMG=debian-13-genericcloud-amd64.qcow2; U=https://cloud.debian.org/images/cloud/trixie/latest
cd $D
wget -q -N $U/$IMG $U/SHA512SUMS
grep " $IMG\$" SHA512SUMS | sha512sum -c - | sed 's/^/  /'
qm create $ID --name squidca --memory 1024 --cores 1 --cpu host --ostype l26 --agent 1 --onboot 1 \
  --net0 virtio,bridge=vmbr0,firewall=1 --scsihw virtio-scsi-single --serial0 socket --vga serial0 \
  --tags "ca;ssh" --description "step-ca SSH certificate authority (OIDC via Authentik). LAN/VPN only. Backed up ONLY to the encrypted PBS storage. Created 2026-11-05."
qm importdisk $ID $D/$IMG local-lvm >/dev/null
qm set $ID --scsi0 local-lvm:vm-$ID-disk-0,discard=on,ssd=1 --boot order=scsi0 --ide2 local-lvm:cloudinit >/dev/null
qm resize $ID scsi0 8G >/dev/null
qm set $ID --ciuser arawn --sshkeys /root/squidca_keys.pub --ipconfig0 ip=10.0.0.55/16,gw=10.0.0.1 --nameserver 10.0.0.61 --searchdomain lan >/dev/null
cat > /etc/pve/firewall/$ID.fw <<'FW'
[OPTIONS]
enable: 1
policy_in: ACCEPT
policy_out: ACCEPT

[RULES] # squidca: step-ca HTTPS from LAN + VPN only
IN ACCEPT -source +lan -p tcp -dport 443
IN ACCEPT -source +vpn -p tcp -dport 443
IN DROP -p tcp -dport 443
GROUP lan-mgmt
FW
qm start $ID
echo "  started; MAC $(qm config $ID | grep -oE 'virtio=[0-9A-F:]+' | cut -d= -f2)"
