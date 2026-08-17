import pytest

from app.models import Dataset, PullRequest, PullRequestStatus, Registry, Repository


SAMPLE_DATASET = {
    "id": 1,
    "name": "My Dataset",
    "host": "https://db.host",
    "port": 5432,
    "schema": "cdm",
    "schema_write": "results",
    "type": "postgres",
    "slug": "my-dataset",
    "url": "https://db.host/my-dataset",
}


class TestDataset:
    def test_secret_name_matches_the_backend_naming(self):
        """Dataset.get_creds_secret_name on the backend produces this name."""
        assert Dataset(**SAMPLE_DATASET).secret_name == "db.host-my-dataset-creds"

    @pytest.mark.parametrize("name,expected", [
        ("My Dataset", "db.host-my-dataset-creds"),
        ("my_dataset", "db.host-my-dataset-creds"),
        ("my#dataset", "db.host-my-dataset-creds"),
        ("UPPER", "db.host-upper-creds"),
    ])
    def test_secret_name_normalises_the_dataset_name(self, name, expected):
        assert Dataset(**{**SAMPLE_DATASET, "name": name}).secret_name == expected

    def test_secret_name_strips_the_scheme_from_the_host(self):
        dataset = Dataset(**{**SAMPLE_DATASET, "host": "http://db.host"})

        assert dataset.secret_name.startswith("db.host-")

    def test_dump_task_fields_are_prefixed(self):
        fields = Dataset(**SAMPLE_DATASET).dump_task_fields()

        assert fields == {
            "dataset_name": "My Dataset",
            "dataset_host": "https://db.host",
            "dataset_port": 5432,
            "dataset_type": "postgres",
            "dataset_schema": "cdm",
            "dataset_schema_write": "results",
            "dataset_secret_name": "db.host-my-dataset-creds",
        }

    def test_dump_task_fields_feed_the_pipes_op_config(self):
        """Every key has to be a k8s_pipes_op config field."""
        from app.definitions.pipes import k8s_pipes_op

        config_fields = set(k8s_pipes_op.config_schema.as_field().config_type.fields)

        assert set(Dataset(**SAMPLE_DATASET).dump_task_fields()) <= config_fields

    def test_unknown_backend_fields_are_kept(self):
        dataset = Dataset(**{**SAMPLE_DATASET, "extra_field": "value"})

        assert dataset.extra_field == "value"


class TestRegistry:
    def make_registry(self, url, reg_id=1):
        return Registry(id=reg_id, url=url)

    @pytest.mark.parametrize("url,expected", [
        ("https://ghcr.io", "ghcr-io"),
        ("http://ghcr.io", "ghcr-io"),
        ("ghcr.io", "ghcr-io"),
        ("ghcr.io/org", "ghcr-io-org"),
        ("my_registry.example.com", "my-registry-example-com"),
    ])
    def test_secret_name_matches_the_backend_slug(self, url, expected):
        """Registry.slugify_name on the backend produces this name."""
        assert self.make_registry(url).secret_name == expected

    def test_matching_registry_wins(self):
        registries = [
            self.make_registry("docker.io", 1),
            self.make_registry("ghcr.io", 2),
        ]

        assert Registry.secret_for_image(
            "ghcr.io/org/experiment:latest", registries
        ) == "ghcr-io"

    def test_shortest_matching_prefix_wins(self):
        registries = [
            self.make_registry("ghcr.io/org", 1),
            self.make_registry("ghcr.io", 2),
        ]

        assert Registry.secret_for_image(
            "ghcr.io/org/experiment:latest", registries
        ) == "ghcr-io"

    def test_registry_host_on_its_own_matches(self):
        registries = [self.make_registry("ghcr.io")]

        assert Registry.secret_for_image("ghcr.io", registries) == "ghcr-io"

    @pytest.mark.parametrize("image", [
        "ghcr.iomalicious/img:1",
        "evil.com/ghcr.io/img:1",
        "docker.io/library/alpine:3",
    ])
    def test_non_matching_images_get_no_secret(self, image):
        registries = [self.make_registry("ghcr.io")]

        assert Registry.secret_for_image(image, registries) is None

    def test_no_registries_configured(self):
        assert Registry.secret_for_image("alpine:3", []) is None

    def test_scheme_is_stripped_before_matching(self):
        registries = [self.make_registry("https://ghcr.io")]

        assert Registry.secret_for_image("ghcr.io/org/img:1", registries) == "ghcr-io"


class TestPullRequestStatus:
    def test_str_is_the_value(self):
        assert str(PullRequestStatus.READY) == "READY"

    def test_status_is_a_string_enum(self):
        assert PullRequestStatus.SUCCESS == "SUCCESS"


class TestRepository:
    def test_pull_requests_default_to_empty(self):
        repo = Repository(
            id=1,
            uri="github.com/org/repo",
            path="org/repo",
            watch_dir="specs/",
            base_branch="main",
            dataset_id=1,
            pr_cursor="2026-01-01T00:00:00Z",
        )

        assert repo.pull_requests == []
        assert repo.pr_count == 0

    def test_nested_pull_requests_are_parsed(self):
        repo = Repository(
            id=1,
            uri="github.com/org/repo",
            path="org/repo",
            watch_dir="specs/",
            base_branch="main",
            dataset_id=1,
            pr_cursor="2026-01-01T00:00:00Z",
            pull_requests=[{
                "repository_id": 1,
                "number": 5,
                "title": "t",
                "raised_by": "dev",
                "merged_at": "2026-06-26T10:00:00Z",
                "merge_commit_sha": "abc",
                "spec": {},
                "status": "UNKNOWN",
            }],
        )

        assert isinstance(repo.pull_requests[0], PullRequest)
        assert repo.pull_requests[0].number == 5
