# FN alpine image

This folder contains few scripts used by the federated node deployment as "assistants" in an alpine base image.

Alpine is used due to the small size and simplicity.

## Tools available

### dbinit.sh
Simple script to initialize a databasae if it doesn't exist already.

This is used as initContainer for keycloak statefulset and backend deployment.
