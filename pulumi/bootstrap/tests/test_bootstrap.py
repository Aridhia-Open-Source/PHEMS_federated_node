from pathlib import Path

import pytest

import bootstrap

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


def test_render_rejects_unresolved_placeholders(tmp_path, monkeypatch):
    (tmp_path / "files").mkdir()
    (tmp_path / "files" / "template.yaml").write_text("value: {{UNKNOWN}}", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "ROOT", tmp_path)

    with pytest.raises(ValueError, match="UNKNOWN"):
        bootstrap._render(
            "template.yaml",
            site="site",
            namespace="fn",
            chart_version="2.0.0",
            release_name="federated-node",
        )


def test_rendered_templates_are_complete():
    for path in bootstrap.FILES:
        rendered = bootstrap._render(
            path,
            site="example-site",
            namespace="example-fn",
            chart_version="2.3.4",
            release_name="example-release",
        )

        assert "{{" not in rendered


def test_rendered_templates_use_configured_values():
    rendered = bootstrap._render(
        "helmrelease.yaml",
        site="example-site",
        namespace="example-fn",
        chart_version="2.3.4",
        release_name="example-release",
    )

    assert "name: example-release" in rendered
    assert "namespace: example-fn" in rendered
    assert 'version: "2.3.4"' in rendered
