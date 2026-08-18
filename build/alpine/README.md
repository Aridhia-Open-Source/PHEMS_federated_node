# FN alpine image

This folder contains few scripts used by the federated node deployment as "assistants" in an alpine base image.

Alpine is used due to the small size and simplicity.

## Tools available

### dbinit.sh
Simple script to initialize a databasae if it doesn't exist already.

This is used as initContainer for keycloak statefulset and backend deployment.

### keycloak-reset.sh
Very important during helm chart upgrades, it deletes few entries related to the `KEYCLOAK_ADMIN` user in order to reset the credentials properly (this might be deprecated when keycloak get updated to v 26.0.0).
After deletion, the new keycloak pods will re-initialize the admin user, and effectively reset the credentials.

