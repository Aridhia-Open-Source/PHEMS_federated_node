import re
from  pytest_asyncio import fixture
from unittest.mock import Mock
from kubernetes_asyncio.client import V1Secret

from app.models.registry import Registry


@fixture
def registry_secret_mock(dockerconfigjson_mock, cr_name):
    secret_return = Mock(spec=V1Secret)
    secret_return.metadata.name = re.sub(r'[\W_]+', '-', cr_name)
    secret_return.data = dockerconfigjson_mock
    return secret_return
