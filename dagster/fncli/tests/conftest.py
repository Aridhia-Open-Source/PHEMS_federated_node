import pytest

ENV = {
    "NAMESPACE": "fn",
    "KEYCLOAK_NAMESPACE": "keycloak",
    "BACKEND_URL": "http://localhost:5000",
    "GITEA_API_URI": "http://gitea.fn.svc:3000/api/v1",
    "TEST_PROJECT_NAME": "proj",
    "TEST_TRIGGER_REPO": "trigger",
    "TEST_TRIGGER_REPO_URI": "http://gitea.fn.svc:3000/gitea_admin/trigger",
    "TEST_TRIGGER_REPO_WATCH_DIR": "specs/",
    "TEST_RESULTS_REPO": "results",
    "TEST_RESULTS_REPO_URI": "http://gitea.fn.svc:3000/gitea_admin/results",
    "TEST_RESULTS_TARGET_DIR": "out/",
    "DEFAULT_PROJECT_DATASET": "cdm",
}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    """Every setting the configs require, as the dev .env provides them."""
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
