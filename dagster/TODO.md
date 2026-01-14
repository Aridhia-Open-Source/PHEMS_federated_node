- Convert definitions to a module and pull in sandbox app code *
- Update dockerfile to install the module and the helm chart commands *
- Test module changes working

---

- Add in Minio as a service for helm deployment
- Update dagster.yaml with config for minio
- Verify succesful materialization with multi-step asset job

---

- Add dagster pipes asset, resources and model code (julia)
- Setup shared PVC mount for dagster pipes parent/child container

---

14/01/2026
- Completed first two steps and now need to make deploy to test