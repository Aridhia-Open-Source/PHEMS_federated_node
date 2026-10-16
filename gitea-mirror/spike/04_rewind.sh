#!/usr/bin/env bash
# Workaround A for PRs whose head is already reachable from the pushed base (merge commit / ff / rebase):
#   force master to merge_commit_sha^1, open PR (base=master), fast-forward master to merge_commit_sha,
#   mark manually-merged, fast-forward master to the tip. (manually-merged needs the commit in the base branch.)
# Usage: 04_rewind.sh <n>
set -u; . "$(dirname "$0")/common.sh"; TOKEN=$(cat /tmp/m0/token); N=$1
H="http.extraHeader=Authorization: token $TOKEN"; R=$G/$ORG/$REPO.git
read LOGIN SHA < <(python3 -c "
import json;x=[x for x in json.load(open('/tmp/m0/prs.json')) if x['number']==$N][0];print(x['user']['login'],x['merge_commit_sha'])")
TIP=$(git -C $SRC rev-parse master)
show() { api GET "$1" | python3 -c "
import sys,json;t=sys.stdin.read();print(t.rsplit('\n',2)[-2]);d=json.loads(t.split('\n',1)[1].rsplit('\nHTTP',1)[0]);print(len(d),'files',[(f['filename'],f['status']) for f in d][:6])"; }
echo "##### PR $N: master -> $SHA^1"
git -C $SRC -c "$H" push --force $R $SHA^1:refs/heads/master 2>&1 | tail -1
SUDO=$LOGIN api POST /repos/$ORG/$REPO/pulls '{"title":"PR '$N' (rewind test)","head":"pr/'$N'","base":"master"}' | python3 -c "
import sys,json;t=sys.stdin.read();p=json.loads(t.split('\n',1)[1].rsplit('\nHTTP',1)[0]);print('created',p.get('number'),p.get('message'),'changed_files',p.get('changed_files'));open('/tmp/m0/idx','w').write(str(p.get('number')))"
IDX=$(cat /tmp/m0/idx)
echo "--- files while open (master at merge^1)"; show "/repos/$ORG/$REPO/pulls/$IDX/files?limit=50"
echo "--- master -> merge commit"; git -C $SRC -c "$H" push $R $SHA:refs/heads/master 2>&1 | tail -1
SUDO=$LOGIN api POST /repos/$ORG/$REPO/pulls/$IDX/merge '{"Do":"manually-merged","MergeCommitID":"'$SHA'"}'
api GET /repos/$ORG/$REPO/pulls/$IDX | python3 -c "
import sys,json;t=sys.stdin.read();p=json.loads(t.split('\n',1)[1].rsplit('\nHTTP',1)[0])
print({k:p.get(k) for k in('number','merged','merged_at','merge_commit_sha','changed_files','additions','deletions','merge_base')})"
echo "--- files after merge (master at merge commit)"; show "/repos/$ORG/$REPO/pulls/$IDX/files?limit=50"
echo "--- master -> tip"; git -C $SRC -c "$H" push $R $TIP:refs/heads/master 2>&1 | tail -1
echo "--- files after master at tip"; show "/repos/$ORG/$REPO/pulls/$IDX/files?limit=50"
