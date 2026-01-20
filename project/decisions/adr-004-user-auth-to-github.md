# ADR 004: User Auth to GitHub

## Status
Proposed

## Context
At the current stage the Federated Node Task Controller (v 1.7.0), the user flow for triggering a task is the following:
- Upon PR merge for the task definition request, the pipeline injects into the json file for the definition the username and the github userid for the PR author.
- Once received through ArgoCD, the task definition will be detected by the Task Controller and will try to link the github user info to the local user management system (Keycloak)

This causes few manual steps in order to be successful:
- The user has to exist in the Federated Node with the permission to access to the dataset
- A secret needs to be created at deployment time so the user identity can be double checked as a pre-execution step

## Decision
It would be preferable to avoid this process entirely and trust GitHub when it comes to user management. Basically, any user that has been granted access to the task trigger repository, will have permissions to access the dataset.

## Implementation
This will be a two stage process:
- The Task Controller will drop the user link step

  Fairly straightforward, the Custom Resource Definition (task definition) annotations for the users will be ignored. And the task will be submitted from the backend user credentials.

- A dataset is linked to a repository

  This is necessary as the Federated Node, without user info can't know which dataset connection information has to be forwarded to the task pod/container.

To allow maximum freedom of choice, the user validation should be behind a feature flag in the helm chart, defaulting to the behaviour proposed in this document.

## Consequences
It should smooth out the process with less hands-on operations on the cluster from the Data Controller.

But this could weaken the security, as currently we use the `/token_transfer` endpoint as another layer only accessible from the cluster, which can't be tampered from external factor.

The endpoint will be still active, but effectively not used as no new users will be created or be necessary. All of the outbound connection operations (between the Task Controller and the FN API, _not the task pod code itself_) will be performed as privileged user.

## Alternatives Considered
This is a binary choice, either have the user-permission validation or not. Currently is used.
