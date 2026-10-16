#!/usr/bin/env bash
# Usage: 03_pr.sh <n>   Create shadow user, open Gitea PR as them, mark manually-merged.
set -u; . "$(dirname "$0")/common.sh"; TOKEN=$(cat /tmp/m0/token)
N=$1
J=$(python3 - <<P
import json;x=[x for x in json.load(open('/tmp/m0/prs.json')) if x['number']==$N][0]
print(json.dumps({k:x[k] for k in('title','body','merged_at','merge_commit_sha','created_at')}|{'login':x['user']['login'],'base':x['base']['ref']}))
P
)
f() { echo "$J" | python3 -c "import sys,json;print(json.load(sys.stdin)['$1'] or '')"; }
LOGIN=$(f login); SHA=$(f merge_commit_sha); BASE=$(f base); TITLE=$(f title)
echo "##### PR $N by $LOGIN merged_at(GitHub)=$(f merged_at) merge_commit_sha=$SHA"
echo "--- shadow user"
api GET /users/$LOGIN | tail -1
api POST /admin/users '{"username":"'$LOGIN'","email":"'$LOGIN'@shadow.invalid","password":"'$(head -c12 /dev/urandom|base64|tr -d '/+=')'Aa1","must_change_password":false,"visibility":"private"}' | tail -1
echo "--- add shadow user as org collaborator (write) so Sudo can open PRs on a private repo"
api PUT /repos/$ORG/$REPO/collaborators/$LOGIN '{"permission":"write"}' | tail -1
echo "--- open PR as shadow user"
SUDO=$LOGIN api POST /repos/$ORG/$REPO/pulls "$(python3 -c "import json,sys;print(json.dumps({'title':sys.argv[1],'head':'pr/$N','base':sys.argv[2],'body':'Mirrored from GitHub PR #$N'}))" "$TITLE" "$BASE")" | cut -c1-600
IDX=$(curl -s -H "Authorization: token $TOKEN" "$G/api/v1/repos/$ORG/$REPO/pulls?state=all&limit=50" | python3 -c "
import sys,json
l=[p['number'] for p in json.load(sys.stdin) if p['head']['ref']=='pr/$N']
print(l[0] if l else '')")
echo "gitea PR index: $IDX"
[ -z "$IDX" ] && exit 0
echo "--- mark manually merged at merge_commit_sha"
SUDO=$LOGIN api POST /repos/$ORG/$REPO/pulls/$IDX/merge '{"Do":"manually-merged","MergeCommitID":"'$SHA'"}'
echo "--- GET pull"
api GET /repos/$ORG/$REPO/pulls/$IDX | python3 -c "
import sys,json
t=sys.stdin.read().rsplit('\nHTTP',1)[0]
try:
  p=json.loads(t.split('\n',1)[1] if t.startswith('>>>') else t)
  print({k:p.get(k) for k in('number','state','merged','merged_at','merge_commit_sha','created_at','closed_at','updated_at','user')} | {'user':p['user']['login'],'head':p['head']['ref'],'base':p['base']['ref'],'changed_files':p.get('changed_files'),'additions':p.get('additions')})
except Exception as e: print(t[:500])"
echo "--- GET files (the Dagster sensors' endpoint)"
api GET "/repos/$ORG/$REPO/pulls/$IDX/files?page=1&limit=50" | python3 -c "
import sys
t=sys.stdin.read(); print(t.split('\n',1)[0]); print(t.rsplit('\nHTTP',1)[1].strip() and 'HTTP'+t.rsplit('\nHTTP',1)[1].strip()); import json
b=t.split('\n',1)[1].rsplit('\nHTTP',1)[0]
try:
  d=json.loads(b); print(len(d),'files:',[(f['filename'],f['status'],f['additions'],f['deletions']) for f in d][:8])
except Exception: print(b[:400])"
