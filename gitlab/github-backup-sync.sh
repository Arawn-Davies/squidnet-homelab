#!/bin/bash
# the git container: nightly backup of every GitHub repo owned by GITHUB_USER into git.lab.example.co.uk/gitlab-user/.
# GitHub stays the primary. This only READS GitHub. Nothing is ever deleted on gitserver:
#  - new repos -> new GitLab projects (CI disabled, same visibility/description)
#  - branches/tags fast-forwarded; branches deleted on GitHub are kept here
#  - force-pushed branches: old tip saved as tag backup/<branch>/<date> before updating
# Tokens (root 600): /root/.github_ro_token (fine-grained, Contents+Metadata read-only)
#                    /root/.gitlab_sync_token (user gitlab-user: api, write_repository)
# Alerts: ntfy topic squidnet-alerts (token /root/.ntfy-alerts.token)
set -uo pipefail
OWNER=GITHUB_USER; NS=gitlab-user; GLH=git.lab.example.co.uk; GL=https://$GLH/api/v4
CACHE=/var/opt/github-backup; LOG=/var/log/github-backup-sync.log; DATE=$(date +%F)
GHT=$(cat /root/.github_ro_token); GLT=$(cat /root/.gitlab_sync_token)
GHH="Authorization: Basic $(printf 'x-access-token:%s' "$GHT" | base64 -w0)"
GLA="Authorization: Basic $(printf 'oauth2:%s' "$GLT" | base64 -w0)"
mkdir -p $CACHE; exec >>$LOG 2>&1
echo "== $(date '+%F %T') start"
alert(){ [ -f /root/.ntfy-alerts.token ] && curl -s -m 10 -H "Authorization: Bearer $(cat /root/.ntfy-alerts.token)" -H "Title: gitserver GitHub backup" -H "Priority: 4" -H "Tags: warning" -d "$1" http://NTFY_HOST:2586/squidnet-alerts >/dev/null || true; }
gl(){ curl -s -H "PRIVATE-TOKEN: $GLT" -H "Content-Type: application/json" "$@"; }
repos=$(python3 - "$GHT" "$OWNER" <<'PY'
import json, sys, urllib.request
tok, owner = sys.argv[1], sys.argv[2]; out = []; page = 1
while True:
    r = urllib.request.Request(f"https://api.github.com/user/repos?affiliation=owner&per_page=100&page={page}",
        headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"})
    b = json.load(urllib.request.urlopen(r, timeout=60))
    if not b: break
    out += [x for x in b if x["owner"]["login"] == owner]; page += 1
for x in out:
    d = (x.get("description") or "").replace("\t", " ").replace("\n", " ")
    print("\t".join([x["name"], "private" if x["private"] else "public", str(x["archived"]).lower(), x.get("default_branch") or "", d]))
PY
) || { alert "GitHub API listing failed (token expired?)"; echo "FAIL list"; exit 1; }
ok=0; fail=0; new=0; forced=0
while IFS=$'\t' read -r name vis arch defb desc; do
  [ -n "$name" ] || continue
  d=$CACHE/$name.git
  [ -d "$d" ] || git init -q --bare "$d"
  if ! git -C "$d" -c http.extraHeader="$GHH" fetch -q --prune --force "https://github.com/$OWNER/$name.git" '+refs/heads/*:refs/heads/*' '+refs/tags/*:refs/tags/*' 2>>$LOG; then
    echo "FAIL fetch $name"; fail=$((fail+1)); continue; fi
  pid=$(gl "$GL/projects/$NS%2F$name" | python3 -c "import json,sys;print(json.load(sys.stdin).get('id',''))")
  if [ -z "$pid" ]; then
    body=$(python3 -c "import json,sys;print(json.dumps({'name':sys.argv[1],'path':sys.argv[1],'namespace_id':sys.argv[2],'visibility':sys.argv[3],'description':(sys.argv[4]+' (copied from github.com/GITHUB_USER/'+sys.argv[1]+')').strip(),'builds_access_level':'disabled','auto_devops_enabled':False}))" "$name" "$NS" "$vis" "$desc")
    pid=$(gl -X POST "$GL/projects" -d "$body" | python3 -c "import json,sys;print(json.load(sys.stdin).get('id',''))")
    [ -n "$pid" ] || { echo "FAIL create $name"; fail=$((fail+1)); continue; }
    new=$((new+1)); echo "NEW  $name"
  fi
  # what gitserver has now
  declare -A have=(); while read -r sha ref; do have[$ref]=$sha; done < <(git -C "$d" -c http.extraHeader="$GLA" ls-remote --heads "https://$GLH/$NS/$name.git" 2>/dev/null)
  # protect history on force-pushed branches
  for ref in "${!have[@]}"; do
    new_sha=$(git -C "$d" rev-parse -q --verify "$ref" 2>/dev/null) || continue
    old=${have[$ref]}
    [ "$old" = "$new_sha" ] && continue
    if git -C "$d" cat-file -e "$old" 2>/dev/null && git -C "$d" merge-base --is-ancestor "$old" "$new_sha"; then continue; fi
    br=${ref#refs/heads/}
    git -C "$d" -c http.extraHeader="$GLA" push -q "https://$GLH/$NS/$name.git" "$old:refs/tags/backup/$br/$DATE" 2>>$LOG && { echo "KEPT $name $br old tip -> tag backup/$br/$DATE"; forced=$((forced+1)); }
  done
  unset have
  # skip the push when gitserver already has exactly these branches/tags (archived projects reject pushes)
  lr=$(git -C "$d" for-each-ref --format='%(objectname) %(refname)' refs/heads refs/tags | sort)
  rr=$(git -C "$d" -c http.extraHeader="$GLA" ls-remote --heads --tags "https://$GLH/$NS/$name.git" 2>/dev/null | grep -v '\^{}$' | awk '{print $1" "$2}' | sort)
  if [ "$lr" = "$rr" ]; then ok=$((ok+1)); continue; fi
  was_arch=$(gl "$GL/projects/$pid" | python3 -c "import json,sys;print(str(json.load(sys.stdin).get('archived')).lower())")
  [ "$was_arch" = true ] && gl -X POST "$GL/projects/$pid/unarchive" >/dev/null
  if git -C "$d" -c http.extraHeader="$GLA" push -q --force "https://$GLH/$NS/$name.git" 'refs/heads/*:refs/heads/*' 'refs/tags/*:refs/tags/*' 2>>$LOG; then
    [ -n "$defb" ] && gl -X PUT "$GL/projects/$pid" -d "{\"default_branch\":\"$defb\"}" >/dev/null
    a=$(gl "$GL/projects/$pid" | python3 -c "import json,sys;print(str(json.load(sys.stdin).get('archived')).lower())")
    [ "$arch" = true ] && [ "$a" = false ] && gl -X POST "$GL/projects/$pid/archive" >/dev/null
    [ "$arch" = false ] && [ "$a" = true ] && gl -X POST "$GL/projects/$pid/unarchive" >/dev/null
    ok=$((ok+1))
  else
    echo "FAIL push $name"; fail=$((fail+1))
    [ "$was_arch" = true ] && gl -X POST "$GL/projects/$pid/archive" >/dev/null
  fi
done <<< "$repos"
echo "== $(date '+%F %T') done: ok=$ok new=$new force-push-tips-kept=$forced fail=$fail"
[ $fail -eq 0 ] || alert "GitHub backup: $fail repo(s) failed, $ok ok. See $LOG on gitserver."
# token expiry warning (30 days)
exp=$(gl "$GL/personal_access_tokens/self" | python3 -c "import json,sys;print(json.load(sys.stdin).get('expires_at') or '')")
[ -n "$exp" ] && [ $(( ($(date -d "$exp" +%s) - $(date +%s)) / 86400 )) -lt 30 ] && alert "gitserver sync token expires $exp - renew it"
exit 0
