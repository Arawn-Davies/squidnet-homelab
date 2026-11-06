set -e
IP=${LANCACHE_IP:?set LANCACHE_IP}; OUT=/etc/dnsmasq.d/30-lancache.conf; T=$(mktemp -d)
curl -fsSL https://raw.githubusercontent.com/uklans/cache-domains/master/cache_domains.json -o $T/cd.json
for svc in steam epicgames blizzard riot origin uplay xboxlive nintendo sony; do
  for f in $(python3 -c "import json,sys;d=json.load(open('$T/cd.json'));print(' '.join(x for c in d['cache_domains'] if c['name']=='$svc' for x in c['domain_files']))"); do
    curl -fsSL "https://raw.githubusercontent.com/uklans/cache-domains/master/$f" >> $T/all.txt; echo >> $T/all.txt
  done
done
{ echo "# LANCache overrides -> the LANCache container ($IP). Generated $(date +%F) from uklans/cache-domains."
  echo "# Services: steam epicgames blizzard riot origin uplay xboxlive nintendo sony (no Windows Update)."
  echo "# address= answers A with the cache. local= makes AAAA (and every other type) NODATA instead of forwarding:"
  echo "# since dnsmasq 2.86 an IPv4-only address= no longer blocks AAAA, so clients would get the real IPv6 CDN and skip the cache."
  grep -vE '^\s*(#|$)' $T/all.txt | sed -E 's/^\*\.//; s/\s+//g' | sort -u | awk -v ip="$IP" '{print "address=/" $0 "/" ip; print "local=/" $0 "/"}'; } > $OUT.new
n=$(grep -c '^address=' $OUT.new); mv $OUT.new $OUT; rm -rf $T
cur=$(pihole-FTL --config misc.etc_dnsmasq_d)
[ "$cur" = true ] || pihole-FTL --config misc.etc_dnsmasq_d true >/dev/null
systemctl restart pihole-FTL
for i in $(seq 1 30); do r=$(dig +short +time=1 @127.0.0.1 lancache.steamcontent.com 2>/dev/null | sed -n '$p'); [ "$r" = "$IP" ] && break; sleep 1; done
r6=$(dig +short AAAA @127.0.0.1 lancache.steamcontent.com)
echo "overrides: $n domains | etc_dnsmasq_d was $cur | lancache.steamcontent.com A -> $r, AAAA -> ${r6:-none (good)} | epic: $(dig +short @127.0.0.1 download.epicgames.com | sed -n '$p') | google (untouched): $(dig +short @127.0.0.1 www.google.com | sed -n 1p)"
