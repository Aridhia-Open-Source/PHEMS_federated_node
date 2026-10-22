# 0023. Outbound TLS trust: a custom CA bundle added to the system CAs, verified, restarted on change

## Context

A client runs the node behind TLS interception, or reaches a git host, an identity provider, a container registry or a proxy that is signed by a private or self-signed CA. The chart handles inbound TLS (`tls.secretName`, cert-manager) and nothing for outbound TLS, so every such call fails certificate verification. Several workloads make outbound HTTPS calls: the webserver (container registry lookups), the Dagster code server and the Dagster run pods (clone and push to the git host, deliver results), and Keycloak (identity providers).

## Decision

- **One value, off by default.** `customCA.secretName` names an existing Secret and `customCA.key` (default `ca.crt`) the key holding the PEM. Or `customCA.pem` holds the PEM and the chart renders a Secret called `fn-custom-ca` from it. Naming a Secret and giving a PEM together is rejected, as is text without a certificate in it. With neither set, the rendered chart is unchanged.
- **The custom CA is added to the system CAs, never substituted.** An init container, running the workload's own image so the system CAs it copies are that image's, concatenates the system bundle and the custom CA into a shared `emptyDir`. The init container fails if the image has no system bundle or the custom CA is empty, rather than build a bundle of the custom CA alone. The workload's tools read the combined file through `REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE`, `CURL_CA_BUNDLE` and `GIT_SSL_CAINFO`. No workload here uses Node, so `NODE_EXTRA_CA_CERTS` is not set.
- **The Secret is mounted as a directory, never through `subPath`,** so the kubelet refreshes it. The key is projected to `ca.crt` whatever it is called in the Secret.
- **Workloads that get it:** the backend; the Dagster code server; every Dagster run pod; Keycloak. Run pods are built by the K8sRunLauncher from the subchart's values, which Helm cannot template. The code server carries the same volumes, init container and env as a Dagster container context (`DAGSTER_CLI_API_GRPC_CONTAINER_CONTEXT`, JSON built from the same helpers), and the launcher applies it to every run launched from that code location. Keycloak uses its own truststore: `KC_TRUSTSTORE_PATHS` points at the PEM mounted from the Secret, and Keycloak keeps trusting the system and JVM CAs, so it needs no init container.
- **Workloads that do not:** task (pipes) pods run partner-supplied code and have no outbound access by design ([ADR 0022](0022-task-isolation.md)); trusting a new CA there would widen what partner code can reach. The backend's database migration, the Keycloak initializer and the credential rotation job call only in-cluster HTTP and Postgres. The Dagster webserver and daemon belong to the Dagster subchart, whose values the chart cannot template; they make no outbound HTTPS calls, since sensors run in the code server and run pods are started through the Kubernetes API with the cluster's own CA.
- **Rotation is a restart.** The combined bundle is built when a pod starts, and the JVM reads its truststore at start. The pod template carries `checksum/custom-ca`: the hash of the inline PEM, or of the named Secret's data when `helm` can read the cluster. A changed CA therefore rolls the pods on `helm upgrade`. A Secret managed outside Helm and changed in place needs `kubectl rollout restart` on the backend and the code server (new run pods pick the change up by themselves) and on Keycloak, or a reloader controller. Where the chart cannot read the cluster (`helm template`, `helm diff`) the hash is of the Secret's name and key only.
- **A Secret you name is copied** into the Keycloak namespace by the chart, as `firstUserSecret` is, since a Secret cannot be mounted across namespaces. Inline PEM is rendered into both namespaces.
- **Verification is never disabled.** There is no option to skip it. The `local_development` flag is unrelated and keeps its meaning.
- **Dev tooling.** `CUSTOM_CA_FILE` in `.dev.env` makes `scripts/deploy.sh` and `scripts/upgrade.sh` create the Secret and set `customCA.secretName` for the dev release. `SANDBOX_CA_FILE` makes `scripts/sandbox.sh` install the CA into the sandbox image's system trust (apt is switched to https and trusts the file for its first run) and point the sandbox shells' curl, pip and git at the system bundle. The inner Docker daemon reads the system trust for registry pulls. Both are best effort and do nothing when unset.

## Consequences

- A client with a private CA sets one value and every outbound call of the listed workloads verifies against the system CAs plus theirs.
- Each affected pod pays one short init container start.
- Node-level trust is not in the chart: the kubelet and containerd pull images with the node's trust store, so a registry behind a private CA needs the CA on every node (containerd's `certs.d` or the node image), which is the cluster operator's job. The same goes for the cluster's own CA for the Kubernetes API, and for kind nodes in the sandbox.
- An external Secret that changes without a `helm upgrade` is not noticed until a restart.
- Adding a workload that calls out means including the same helpers.

## Alternatives considered

- **Skip verification (`verify=False`, `GIT_SSL_NO_VERIFY`, `--insecure`):** removes the protection TLS gives to the credentials these calls carry, and is easy to leave on. Rejected.
- **Replace the system CAs with the custom CA:** breaks every public endpoint the same workload reaches (the git host on the internet next to a private identity provider). Rejected.
- **Bake the CA into the images:** a rebuild per client, and the images are shared.
- **Mount the Secret with `subPath` or mount the bundle directly:** a `subPath` mount is never refreshed, and a directory holding only the custom CA, pointed at by `SSL_CERT_FILE`, would replace the system CAs.
- **Add the CA to the dagster subchart values:** not templated, so it could not follow `customCA`, and the default render would change.
- **Task pods also trust it:** see above; partner code has no outbound access to trust anything for.

## Open questions

- The Dagster daemon and webserver are not given the CA. If one of them gains an outbound HTTPS call, it needs the subchart's own volume, init container and env values (set by hand, because they cannot be templated).
