#!/usr/bin/env bash
# Push branches as-is and PR heads as pr/<n>; then test pushing refs/pull/* directly (Q4).
set -u; . "$(dirname "$0")/common.sh"; TOKEN=$(cat /tmp/m0/token)
R=$G/$ORG/$REPO.git
H="http.extraHeader=Authorization: token $TOKEN"
cd $SRC
git branch -a | head; 
echo "--- push branches as-is"
git -c "$H" push $R 'refs/heads/*:refs/heads/*' 2>&1 | tail -3
echo "--- push each PR head as pr/<n>"
git -c "$H" push $R 'refs/pull/*/head:refs/heads/pr/*' 2>&1 | grep -c '\[new branch\]'
echo "--- push tags"
git -c "$H" push $R 'refs/tags/*:refs/tags/*' 2>&1 | tail -1
echo "--- Q4: push refs/pull/140/head directly into a NORMAL repo"
git -c "$H" push $R refs/pull/140/head:refs/pull/140/head 2>&1 | tail -4
