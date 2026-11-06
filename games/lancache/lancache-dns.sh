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
  grep -vE '^\s*(#|$)' $T/all.txt | sed -E 's/^\*\.//; s/\s+//g' | sort -u | sed "s#.*#address=/&/$IP#"; } > $OUT.new
n=$(grep -c '^address=' $OUT.new); mv $OUT.new $OUT; rm -rf $T
cur=$(pihole-FTL --config misc.etc_dnsmasq_d)
[ "$cur" = true ] || pihole-FTL --config misc.etc_dnsmasq_d true >/dev/null
systemctl restart pihole-FTL
for i in $(seq 1 30); do r=$(dig +short +time=1 @127.0.0.1 lancache.steamcontent.com 2>/dev/null | tail -1); [ "$r" = "$IP" ] && break; sleep 1; done
echo "overrides: $n domains | etc_dnsmasq_d was $cur | lancache.steamcontent.com -> $r | epic: $(dig +short @127.0.0.1 download.epicgames.com | tail -1) | google (untouched): $(dig +short @127.0.0.1 www.google.com | head -1)"
