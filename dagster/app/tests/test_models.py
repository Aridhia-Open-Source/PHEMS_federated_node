import pytest

from app.models import Dataset, PullRequest, PullRequestStatus, Registry, TriggerRepository
from app.models import Secret, SecretProviderType
from app.tests.conftest import SAMPLE_DATASET, SAMPLE_SECRET


class TestSecret:
    def test_parses_a_webserver_payload(self):
        secret = Secret(**SAMPLE_SECRET)

        assert secret.provider is SecretProviderType.K8S
        assert (secret.key, secret.namespace, secret.label) == ("git-token-abc", "fn", "git-token")

    def test_namespace_and_description_are_optional(self):
        secret = Secret(id=1, project_id=1, label="l", provider="K8S", key="k")

        assert secret.namespace is None and secret.description is None

    def test_unknown_provider_is_rejected(self):
        with pytest.raises(ValueError):
            Secret(**{**SAMPLE_SECRET, "provider": "VAULT"})

    def test_unknown_fields_are_kept(self):
        assert Secret(**{**SAMPLE_SECRET, "extra": 1}).extra == 1


class TestDataset:
    def test_secret_is_nested(self):
        dataset = Dataset(**SAMPLE_DATASET)

        assert isinstance(dataset.secret, Secret)
        assert dataset.secret.key == "git-token-abc"

    def test_secret_is_required(self):
        payload = {k: v for k, v in SAMPLE_DATASET.items() if k != "secret"}

        with pytest.raises(ValueError):
            Dataset(**payload)

    def test_schemas_are_optional(self):
        dataset = Dataset(**{**SAMPLE_DATASET, "read_schema": None, "write_schema": None})

        assert dataset.read_schema is None and dataset.write_schema is None

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


class TestTriggerRepository:
    def test_pull_requests_default_to_empty(self):
        repo = TriggerRepository(
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
        repo = TriggerRepository(
            id=1,
            uri="github.com/org/repo",
            path="org/repo",
            watch_dir="specs/",
            base_branch="main",
            dataset_id=1,
            pr_cursor="2026-01-01T00:00:00Z",
            pull_requests=[{
                "trigger_repository_id": 1,
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
