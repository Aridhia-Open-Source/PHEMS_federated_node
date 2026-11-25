from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]


def test_all_bootstrap_files_exist():
    expected = {
        "README.md",
        "kustomization.yaml",
        "namespaces.yaml",
        "helmrepository.yaml",
        "helmrelease.yaml",
        "values.yaml",
        "kustomizeconfig.yaml",
    }
    assert {path.name for path in (ROOT / "files").iterdir()} == expected


@pytest.mark.parametrize(
    "placeholder", ("{{SITE}}", "{{NAMESPACE}}", "{{CHART_VERSION}}", "{{RELEASE_NAME}}")
)
def test_templates_use_only_known_placeholders(placeholder):
    content = "\n".join(
        path.read_text(encoding="utf-8") for path in (ROOT / "files").iterdir()
    )
    assert content.count(placeholder) > 0
