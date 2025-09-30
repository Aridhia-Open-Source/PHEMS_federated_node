import os
import requests
import time
from kubernetes import client, config


MAX_RETRIES = 20
MAX_REPLICAS = int(os.getenv("KC_REPLICAS", "2"))

def health_check():
    """
    Checks Keycloak's pod ready state, as the normal health_check
    is not enough, and 1+ replicas can reset progress.
    """
    print("Checking on keycloak's pod's ready state")
    if os.getenv('KUBERNETES_SERVICE_HOST'):
        # Get configuration for an in-cluster setup
        config.load_incluster_config()
    elif os.path.exists(config.KUBE_CONFIG_DEFAULT_LOCATION):
        # Get config from outside the cluster. Mostly DEV
        config.load_kube_config()
    else:
        return

    k8s = client.CoreV1Api()
    for i in range(1, MAX_RETRIES):
        kc_pods = k8s.list_namespaced_pod(label_selector="app=keycloak", namespace=os.getenv("KC_NAMESPACE")).items
        if len([pod.metadata.name for pod in kc_pods if pod.status.container_statuses[0].ready]) < MAX_REPLICAS:
            print("Not all pods ready")
        else:
            break

        if i == MAX_RETRIES:
            print("Max retries reached. Keycloak pods not ready")
            exit(1)

        print("Retrying status in 10 seconds")
        time.sleep(10)


def login(kc_url:str, kc_pass:str) -> str:
    """
    Common login function, gets the url and the password as the user is always the same.
    Returns the access_token
    """
    print("Logging in...")
    url = f"{kc_url}/realms/master/protocol/openid-connect/token"
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    response = requests.post(url, headers=headers, data={
        'client_id': 'admin-cli',
        'grant_type': 'password',
        'username': 'admin',
        'password': kc_pass
    })
    if not response.ok:
        print(response.json())
        exit(1)

    print("Successful")
    return response.json()["access_token"]
