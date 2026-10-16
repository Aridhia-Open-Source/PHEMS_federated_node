#!/usr/bin/env bash
# Q4: Gitea pull mirror (git only, no token) of the same GitHub repo; what refs does it hold, can it hold PRs?
set -u; . "$(dirname "$0")/common.sh"; TOKEN=$(cat /tmp/m0/token); H="http.extraHeader=Authorization: token $TOKEN"
api POST /repos/migrate '{"clone_addr":"https://github.com/backstage/mkdocs-monorepo-plugin.git","service":"git","mirror":true,"repo_owner":"'$ORG'","repo_name":"pullmirror","private":true,"mirror_interval":"8h"}' | cut -c1-250
sleep 15
echo "--- repo flags"
api GET /repos/$ORG/pullmirror | python3 -c "
import sys,json;t=sys.stdin.read();p=json.loads(t.split('\n',1)[1].rsplit('\nHTTP',1)[0]);print({k:p.get(k) for k in('mirror','empty','has_pull_requests','default_branch','size')})"
echo "--- refs held by the pull mirror (git ls-remote, pull/* count + sample)"
git -c "$H" ls-remote $G/$ORG/pullmirror.git > /tmp/m0/pm_refs.txt; awk '{print $2}' /tmp/m0/pm_refs.txt | sed -E 's#refs/pull/[0-9]+/.*#refs/pull/N/*#' | sort | uniq -c | sort -rn | head
echo "--- open a Gitea PR in the mirror"
SUDO=davidxia api PUT /repos/$ORG/pullmirror/collaborators/davidxia '{"permission":"write"}' | tail -1
SUDO=davidxia api POST /repos/$ORG/pullmirror/pulls '{"title":"t","head":"agentbellnorm-patch-2","base":"master"}' | cut -c1-300
