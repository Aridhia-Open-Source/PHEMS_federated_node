import pytest

from app.models import Dataset, PullRequest, TriggerRepository


SAMPLE_DATASET = {
    "id": 1,
    "project_id": 1,
    "name": "My Dataset",
    "host": "https://db.host",
    "port": 5432,
    "k8s_secret_name": "my-dataset-creds",
    "read_schema": "cdm",
    "write_schema": "results",
    "type": "postgres",
    "slug": "my-dataset",
    "url": "https://db.host/my-dataset",
}


class TestDataset:
    def test_dump_task_fields_are_prefixed(self):
        fields = Dataset(**SAMPLE_DATASET).dump_task_fields()

        assert fields == {
            "dataset_name": "My Dataset",
            "dataset_host": "https://db.host",
            "dataset_port": 5432,
            "dataset_type": "postgres",
            "dataset_read_schema": "cdm",
            "dataset_write_schema": "results",
            "dataset_k8s_secret_name": "my-dataset-creds",
        }

    def test_dump_task_fields_feed_the_pipes_op_config(self):
        """Every key has to be a k8s_pipes_op config field."""
        from app.definitions.pipes import k8s_pipes_op

        config_fields = set(k8s_pipes_op.config_schema.as_field().config_type.fields)

        assert set(Dataset(**SAMPLE_DATASET).dump_task_fields()) <= config_fields

    def test_unknown_backend_fields_are_kept(self):
        dataset = Dataset(**{**SAMPLE_DATASET, "extra_field": "value"})

        assert dataset.extra_field == "value"


class TestTriggerRepository:
    def test_pull_requests_default_to_empty(self):
        repo = TriggerRepository(
            id=1,
            uri="github.com/org/repo",
            path="org/repo",
            provider="github",
            api_uri="https://api.github.com",
            k8s_secret_name="org-repo-token",
            watch_dir="specs/",
            base_branch="main",
            project_id=1,
            dataset_id=1,
            pr_cursor="2026-01-01T00:00:00Z",
        )

        assert repo.pull_requests == []
        assert repo.pr_count == 0

    def test_nested_pull_requests_are_parsed(self):
        repo = TriggerRepository(
            id=1,
            uri="github.com/org/repo",
            path="org/repo",
            provider="github",
            api_uri="https://api.github.com",
            k8s_secret_name="org-repo-token",
            watch_dir="specs/",
            base_branch="main",
            project_id=1,
            dataset_id=1,
            pr_cursor="2026-01-01T00:00:00Z",
            pull_requests=[{
                "trigger_repository_id": 1,
                "number": 5,
                "title": "t",
                "raised_by": "dev",
                "merged_at": "2026-06-26T10:00:00Z",
                "merge_commit_sha": "abc",
                "payload": {},
                "state": "UNKNOWN",
            }],
        )

        assert isinstance(repo.pull_requests[0], PullRequest)
        assert repo.pull_requests[0].number == 5
