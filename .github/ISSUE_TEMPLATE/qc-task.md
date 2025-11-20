---
name: QC task
about: Issue that are assigned to QC. It will make sure that what is needed to be testsed is listed. And QC reporting section
title: "[QC]"
labels: ''
assignees: ''

---
Endpoints to be tested:

|Endpoint|Method|Needs Auth|Body example|Admin only?|
|--------|------|----------|------------|-----------|
| | | | | |

---
Acceptance Criteria:

---
QC notes:

```sh
VERSION=
helm repo update
helm upgrade federatednode federatednode/federated-node -n qcfederatednode --reuse-values --version $VERSION
```
