# Node secrets

A **NodeSecret** is a nexus-api secret (git credentials, a database login) given by reference: it names the Kubernetes Secret its values are in, never the values. The operator reads that Secret and writes the values to nexus-api. This page is for the admin who sets them up. For the rest of the node's config, see [Node config](./Node-Config).

The design is in [ADR 0032](https://github.com/Aridhia-Open-Source/PHEMS_federated_node/blob/main/project/decisions/0032-declarative-node-config-through-an-operator.md).


## Name the Secret

A NodeSecret's name is the nexus-api secret label that repositories and datasets refer to. It takes one of two forms:

```yaml
nodeConfig:
  secrets:
    # Every key of the Secret, under the same names
    analysis-repo-creds:
      fromSecret: {name: analysis-github-app}
    # Chosen keys, from one or more Secrets
    omop-db-creds:
      values:
        USERNAME: {secretKeyRef: {name: omop-db, key: user}}
        PASSWORD: {secretKeyRef: {name: omop-db, key: password}}
```

The keys nexus-api expects:

| For | Keys |
|---|---|
| A GitHub App | `APP_ID`, `INSTALLATION_ID`, `PRIVATE_KEY` |
| A Gitea OAuth app | `CLIENT_ID`, `CLIENT_SECRET`, `REFRESH_TOKEN` |
| A dataset's database login | `USERNAME`, `PASSWORD` |


## Where the Secret lives

- In the NodeSecret's own namespace: `fn-operator` for `nodeConfig`. The operator reads Secrets nowhere else.
- Never the release namespace. The operator has no access to it, so a NodeSecret cannot copy the node's own credentials (Keycloak, the database) into nexus-api.
- Values never appear in a resource's status, its events or the operator's log.

Fill the Secret however the site manages secrets: External Secrets from a vault, SOPS-encrypted files in the site repository, or by hand:

```sh
kubectl create secret generic analysis-github-app -n fn-operator \
  --from-literal=APP_ID=<app id> --from-literal=INSTALLATION_ID=<installation id> \
  --from-file=PRIVATE_KEY=<app>.private-key.pem
```

A NodeSecret whose Secret is missing shows `Synced` false and says so in `Message` (`kubectl get nodesecrets -n fn-operator`). Create the Secret and the operator picks it up within a minute.


## Rotate a value

Change the Kubernetes Secret. The operator checks every NodeSecret's Secret every `operator.syncIntervalSeconds` (60 by default) and writes a changed value to nexus-api. Work already running gets the new value.


The operator reads only the Secrets its NodeSecrets name, in the operator namespace. External Secrets and SOPS can create those source Secrets; the operator does not need to know where a value came from.
