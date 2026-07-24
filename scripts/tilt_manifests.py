#!/usr/bin/env python3
"""Emit the K8s deployment manifests Tilt should manage for live development.

Helm (`make deploy`) owns the real cluster state. Tilt only needs the two
deployments whose images we rebuild so it can inject freshly built images and
live_update code into the running containers.

Transformations applied for dev workflow:

  * imagePullPolicy Always -> IfNotPresent, so the kind node uses the image we
    just pushed to the local registry instead of trying to pull it.

  For the backend deployment:
      - Drop initContainers (dbinit/db-migrations/storage-init). They
        already ran during the initial `make deploy`, and the DB + results PV
        persist, so the dev pod only needs the long-running server.

  For the dagster user-deployment:
      - Clear args field so the Kubernetes container won't append them to the
        injected entrypoint (which already includes the args from Helm).

Usage: tilt_manifests.py <namespace> <backend-deploy> <dagster-deploy>
"""
import json
import subprocess
import sys


def main():
    ns, backend, dagster = sys.argv[1], sys.argv[2], sys.argv[3]

    out = subprocess.run(
        ["kubectl", "get", "deployment", backend, dagster, "-n", ns, "-o", "json"],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        # No deployments yet (e.g. before `make deploy`): emit empty list.
        items = []
    else:
        doc = json.loads(out.stdout)
        items = doc.get("items", [doc])

    for item in items:
        name = item["metadata"]["name"]
        spec = item["spec"]["template"]["spec"]

        for container in spec.get("containers", []) + spec.get("initContainers", []):
            if container.get("imagePullPolicy") == "Always":
                container["imagePullPolicy"] = "IfNotPresent"

        if name == backend:
            spec.pop("initContainers", None)

        if name == dagster:
            for container in spec.get("containers", []):
                container["args"] = []

    print(json.dumps({"apiVersion": "v1", "kind": "List", "items": items}))


if __name__ == "__main__":
    main()
