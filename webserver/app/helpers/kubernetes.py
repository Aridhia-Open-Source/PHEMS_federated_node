import base64
import os
import logging
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException
from app.helpers.exceptions import KubernetesException

logger = logging.getLogger('kubernetes_helper')
logger.setLevel(logging.INFO)


class KubernetesBase:
    def __init__(self) -> None:
        if os.getenv('KUBERNETES_SERVICE_HOST'):
            # Get configuration for an in-cluster setup
            config.load_incluster_config()
        else:
            # Get config from outside the cluster. Mostly DEV
            config.load_kube_config()
        super().__init__()

    @classmethod
    def encode_secret_value(cls, value:str) -> str:
        """
        Given a plain text secret it will perform the
        base64 encoding
        """
        return base64.b64encode(value.encode()).decode()

    @classmethod
    def decode_secret_value(cls, value:str) -> str:
        """
        Given a plain text secret it will perform the
        base64 decoding
        """
        return base64.b64decode(value.encode()).decode()


class KubernetesClient(KubernetesBase, client.CoreV1Api):
    def create_secret(self, name:str, values:dict[str, str], namespaces:list, type:str='Opaque', labels:dict={}, overwrite:bool=False) -> client.V1Secret:
        """
        From a dict of values, encodes them,
            and creates a secret in a given list of namespace
            keeping the same structure as values

        overwrite decides what an already existing secret means. Left off, it is kept:
        a create that lost a race should not clobber the winner. Turned on, the values
        passed here win, for callers that are the authority on the content - a secret
        that survives what it describes otherwise goes on serving credentials that no
        longer work.
        """
        body = client.V1Secret()
        body.api_version = 'v1'
        for key in values.keys():
            values[key] = KubernetesClient.encode_secret_value(values[key])

        body.data = values
        body.kind = 'Secret'
        body.metadata = {
            'name': name,
            'labels': labels
        }
        body.type = type
        for ns in namespaces:
            try:
                self.create_namespaced_secret(ns, body=body, pretty='true')
            except ApiException as e:
                if e.status != 409:
                    raise KubernetesException(e.body)
                if overwrite:
                    try:
                        # PATCH, not PUT: the backend role grants `patch` on secrets but
                        # not `update`, so replace_namespaced_secret is always a 403.
                        self.patch_namespaced_secret(name, ns, body=body, pretty='true')
                    except ApiException as exc:
                        raise KubernetesException(exc.body) from exc
        return body
