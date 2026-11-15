from unittest.mock import MagicMock

import pytest

from fncli.backend import FncliBackendAPI


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def api(session):
    return FncliBackendAPI(session=session, logger=MagicMock())


@pytest.mark.parametrize("method, path", [
    ("delete_dataset", "/global/datasets/3"),
    ("delete_repository", "/global/repositories/triggers/3"),
    ("delete_results_repository", "/global/repositories/results/3"),
])
class TestDeletes:
    def test_force_by_default(self, api, session, method, path):
        getattr(api, method)(3)

        session.delete.assert_called_once_with(path, params={"force": "true"})

    def test_without_force(self, api, session, method, path):
        getattr(api, method)(3, force=False)

        session.delete.assert_called_once_with(path, params=None)
