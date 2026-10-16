#!/usr/bin/env bash
# Start Gitea (tag from k8s/federated-node/values.yaml: gitea/gitea:28.1.0) and fetch the public GitHub repo, no token.
set -eu; mkdir -p /tmp/m0; cd /tmp/m0
docker rm -f gitea-spike-m0 >/dev/null 2>&1 || true
docker run -d --name gitea-spike-m0 -p 127.0.0.1:3917:3000 -e GITEA__security__INSTALL_LOCK=true \
  -e GITEA__server__ROOT_URL=http://localhost:3917/ -e GITEA__database__DB_TYPE=sqlite3 gitea/gitea:28.1.0
curl -s "https://api.github.com/repos/backstage/mkdocs-monorepo-plugin/pulls?state=closed&per_page=100" > prs.json   # 1 API call
git clone -q --mirror https://github.com/backstage/mkdocs-monorepo-plugin.git src.git
git -C src.git fetch -q origin '+refs/pull/*/head:refs/pull/*/head'
# then: 01_setup.sh, 02_push.sh, 03_pr.sh <n> (naive), 04_rewind.sh <n> (works), 05_pullmirror.sh; cleanup: docker rm -f gitea-spike-m0
