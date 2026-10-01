# FN alpine image

This folder contains few scripts used by the federated node deployment as "assistants" in an alpine base image.

Alpine is used due to the small size and simplicity.

## Tools available
### cleanup.sh
Takes care of cleaning up the shared storage, old tasks' pod, persistent volumes and claims.

The criteria is set by the `CLEANUP_AFTER_DAYS` environment variable, inherited by the helm chart value `cleanupTime`.

This is run as part of the CronJob `result-cleaner`.

### dbinit.sh
Simple script to initialize a databasae if it doesn't exist already.

This is used as initContainer for keycloak statefulset and backend deployment.

### sync-registry.sh
Another cronJob script, this time for `sync-registry`.

It gets a token for the backend, and then triggers the `/containers/sync` endpoint to keep the list of available images in the whitelisted registry updated.
