from unittest.mock import Mock

from app.helpers.kubernetes import KubernetesBase

class MockKubernetesClient(KubernetesBase):
    secrets = {}
    def read_namespaced_secret(self, namespace, body, pretty, **kwargs):
        return Mock(
            data={'PGUSER': 'YWJjMTIz', 'PGPASSWORD': 'YWJjMTIz'}
        )

    def create_namespaced_secret(self, namespace, body, pretty):
        return Mock()

    def create_namespaced_pod(self, **kwargs):
        return Mock()

    def delete_namespaced_pod(self, pod_name, **kwargs):
        return Mock()

    def create_persistent_volume(self, **kwargs):
        return Mock()

    def create_namespaced_persistent_volume_claim(self, namespace, **kwargs):
        return Mock()

    def list_namespaced_pod(self, namespace, **kwargs):
        obj = Mock(name='namespace_list_pod')
        obj.items = []
        return obj

    def create_secret(self, name:str, data:dict, namespaces:list=["default"]):
        self.secrets[name] = data

    def get_secret(self, name:str,namespaces:list=["default"]):
        return self.secrets[name]

class MockKubernetesBatchClient(KubernetesBase):
    def create_namespaced_job(self, **kwargs):
        return Mock()

    def delete_namespaced_job(self, **kwargs):
        return Mock()
