###
# Migrates the single dockerconfig secret to individual
# ones for better isolation/security
###
import os
import sys
import re
import base64
import json
import requests
import time
from kubernetes import client, config
from kubernetes.client.exceptions import ApiException


BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:5000")
ADMIN_USER = os.getenv("KEYCLOAK_ADMIN")
ADMIN_PASS = os.getenv("KEYCLOAK_ADMIN_PASSWORD")
BACKEND_NAMESPACE = os.getenv("DEFAULT_NAMESPACE", "qcfederatednode")
TASK_NAMESPACE = os.getenv("TASK_NAMESPACE", "tasks")

# Ready check on backend
for i in range(10):
  hc_resp = requests.get(f"{BACKEND_URL}/health_check")
  if hc_resp.ok:
    break

  time.sleep(1)

# Login
login_resp = requests.post(
  f"{BACKEND_URL}/login",
  data={
    "username": ADMIN_USER,
    "password": ADMIN_PASS,
  },
  headers={"Content-Type": "application/x-www-form-urlencoded"}
)
if not login_resp.ok:
  print("Failed to login")
  sys.exit(1)

bearer_token = login_resp.json()["token"]

# Get list of registries
reg_resp = requests.get(
  f"{BACKEND_URL}/registries",
  headers={"Content-Type": "application/x-www-form-urlencoded", "Authorization": f"Bearer {bearer_token}"}
)
if not reg_resp.ok:
  print(reg_resp.json())
  sys.exit(1)

registries = reg_resp.json()["items"]

# Check for kubectl config
if os.getenv('KUBERNETES_SERVICE_HOST'):
    # Get configuration for an in-cluster setup
    config.load_incluster_config()
else:
    # Get config from outside the cluster. Mostly DEV
    config.load_kube_config()

v1_client = client.CoreV1Api()

# Loop through register's secrets and create a docker one
for reg in registries:
  secret_name: str = re.sub(r'[\W_]+','-', reg["url"].lower())
  secret: client.V1Secret = v1_client.read_namespaced_secret(name=secret_name, namespace=BACKEND_NAMESPACE)

  psw_key = base64.b64decode(secret.data["TOKEN"]).decode()
  usr_key = base64.b64decode(secret.data["USER"]).decode()

  matches = re.search(r'azurecr\.io|ghcr\.io', reg["url"])
  matches = '' if matches is None else matches.group()

  if matches:
    key = reg["url"]
  else:
    key = "https://index.docker.io/v1/"

  body = client.V1Secret()
  body.api_version = 'v1'
  body.kind = 'Secret'
  body.type = "kubernetes.io/dockerconfigjson"
  body.metadata = {
    "name": secret_name,
    "labels": {
      "url": secret_name,
      "type": "registry"
    }
  }
  auths = json.dumps({"auths" : {
      key: {
        "username": usr_key,
        "password": psw_key,
        "email": "",
        "auth": base64.b64encode(f"{usr_key}:{psw_key}".encode()).decode()
      }
    }})
  body.data = {".dockerconfigjson": base64.b64encode(auths.encode()).decode()}
  try:
    v1_client.create_namespaced_secret(TASK_NAMESPACE, body)
  except ApiException as apie:
    if apie.status == 409:
      pass
    else:
      print(apie.body)
      sys.exit(1)

  print(f"{secret_name} created!")

print("Done!")
