#!/usr/bin/env python3
"""Emit the K8s deployment manifests Tilt should manage for live development.

Helm (`mise run deploy`) owns the real cluster state. Tilt only needs the
deployments whose images we rebuild so it can inject freshly built images and
live_update code into the running containers.

Transformations applied for dev workflow:

  * imagePullPolicy Always -> IfNotPresent, so the kind node uses the image we
    just pushed to the local registry instead of trying to pull it.

  For the nexus-api deployment:
      - Drop initContainers (wait-for-db, db-migrations). They already ran
        during the initial `mise run deploy`, and the DB persists, so the dev pod
        only needs the long-running server.

  The dagster user-deployment gets DAGSTER_CURRENT_IMAGE pointed at RUN_IMAGE_TAG. Run
  pods start from that image, not from the one Tilt live-updates, and the Tiltfile's
  dagster-run-image resource rebuilds it on every code change.

  The dagster user-deployment keeps the args Helm gave it: the image has no
  entrypoint, so they are the command that Tilt's restart wrapper runs.

Usage: tilt_manifests.py <namespace> <nexus-api-deploy> <dagster-deploy> <nexus-ui-deploy> <operator-namespace> <nexus-operator-deploy>

The operator runs in its own namespace (chart global.namespaces.operator), so it is fetched from there.

nexus-ui and the operator are optional in the chart (nexus.ui.enabled, operator.enabled), so a missing one is
skipped.
"""
import json
import subprocess
import sys

RUN_IMAGE_TAG = "tilt-run"


def get_deployments(ns: str, *names: str) -> list:
    out = subprocess.run(
        ["kubectl", "get", "deployment", *names, "-n", ns, "--ignore-not-found", "-o", "json"],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0 or not out.stdout.strip():
        # No deployments yet (e.g. before `mise run deploy`): none.
        return []
    doc = json.loads(out.stdout)
    return doc.get("items", [doc])


def main():
    ns, nexus_api, dagster, nexus_ui, operator_ns, nexus_operator = sys.argv[1:]

    items = get_deployments(ns, nexus_api, dagster, nexus_ui) + get_deployments(operator_ns, nexus_operator)

    for item in items:
        name = item["metadata"]["name"]
        spec = item["spec"]["template"]["spec"]

        for container in spec.get("containers", []) + spec.get("initContainers", []):
            if container.get("imagePullPolicy") == "Always":
                container["imagePullPolicy"] = "IfNotPresent"

        if name == dagster:
            for container in spec["containers"]:
                for env in container.get("env", []):
                    if env["name"] == "DAGSTER_CURRENT_IMAGE":
                        env["value"] = env["value"].rsplit(":", 1)[0] + ":" + RUN_IMAGE_TAG

        if name == nexus_api:
            spec.pop("initContainers", None)

    print(json.dumps({"apiVersion": "v1", "kind": "List", "items": items}))


if __name__ == "__main__":
    main()
