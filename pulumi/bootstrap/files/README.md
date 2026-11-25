# {{SITE}} deployment

This repository is managed by Pulumi and consumed by Flux.

* `helmrelease.yaml` pins the Federated Node chart.
* `values.yaml` contains non-secret site configuration.
* Secrets must be added as SOPS-encrypted files or ExternalSecrets; never
  commit credentials here.

Pulumi may be run repeatedly. It owns the files in this repository and
updates them in place.
