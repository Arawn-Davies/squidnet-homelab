#!/bin/bash
# Copy NODE2 traffic to vmbr9 for Suricata (CT138 squidids). Idempotent; run every minute by ids-mirror.timer.
# Excluded by MAC (IPv4+IPv6): private containers (never inspected), the backup target (bulk),
# and flareon on nic0 (its traffic is taken from its own veth instead, so nothing is seen twice).
P1=${PRIVATE_CT1_MAC}; P2=${PRIVATE_CT2_MAC}; B1=${BACKUP_CT_MAC}; F1=${FLAREON_MAC}
apply(){ dev=$1; shift
  ip link show "$dev" >/dev/null 2>&1 || return 0
  if tc filter show dev "$dev" ingress 2>/dev/null | grep -q mirred && tc filter show dev "$dev" egress 2>/dev/null | grep -q mirred; then return 0; fi
  tc qdisc del dev "$dev" clsact 2>/dev/null || true
  tc qdisc add dev "$dev" clsact
  for dir in ingress egress; do p=1
    for mac in "$@"; do
      tc filter add dev "$dev" $dir prio $p protocol all flower src_mac "$mac" action ok; p=$((p+1))
      tc filter add dev "$dev" $dir prio $p protocol all flower dst_mac "$mac" action ok; p=$((p+1))
    done
    tc filter add dev "$dev" $dir prio 100 protocol all matchall action mirred egress mirror dev vmbr9
  done
  logger -t ids-mirror "mirroring $dev -> vmbr9 (excluded MACs: $*)"
}
ip link show vmbr9 >/dev/null 2>&1 || exit 0
apply nic0 $P1 $P2 $B1 $F1
apply veth118i0 $P1 $P2
