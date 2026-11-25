from fednode.clients.nexus.client import BackendAPI


class FncliBackendAPI(BackendAPI):
    """The nexus-api client, with the forced deletes only the dev CLI makes: force takes every project's resource too."""

    def delete_dataset(self, dataset_id: int, force: bool = True) -> None:
        """Delete a dataset, and with force every project's resource for it, else a 409 names the projects"""
        self.logger.info(f"Deleting dataset {dataset_id}")
        self.session.delete(f"/global/datasets/{dataset_id}", params={"force": "true"} if force else None)

    def delete_repository(self, repo_id: int, force: bool = True) -> None:
        """Delete a global trigger repository, and with force every project's resource for it, else a 409 names the projects"""
        self.logger.info(f"Deleting trigger repository {repo_id}")
        self.session.delete(f"/global/repositories/triggers/{repo_id}", params={"force": "true"} if force else None)

    def delete_results_repository(self, repo_id: int, force: bool = True) -> None:
        """Delete a global results repository, and with force every project's resource for it, else a 409 names the projects"""
        self.logger.info(f"Deleting results repository {repo_id}")
        self.session.delete(f"/global/repositories/results/{repo_id}", params={"force": "true"} if force else None)
