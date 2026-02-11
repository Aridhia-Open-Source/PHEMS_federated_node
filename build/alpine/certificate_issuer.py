# Script to create the issuer in case
# .Values.global.copySecretsWithTemplate is set to false
# Aims to do the same job as the issuer.yaml template

import os
from dotenv import load_dotenv, find_dotenv
import yaml

load_dotenv(dotenv_path=find_dotenv(usecwd=True))

AWS_CLOUD = {
  "acme": {
    "server": "https://acme-staging-v02.api.letsencrypt.org/directory",
    "email": os.getenv("EMAIL_CERT"),
    "privateKeySecretRef": {
      "name": "letsencrypt-staging"
    },
    "solvers": [{
      "dns01": {
        "route53": {
          "region": os.getenv("REGION"),
          "role": f"arn:aws:iam::{os.getenv("ACCOUNT_ID")}:role/{os.getenv("ROLE_ID")}",
          "auth": {
            "kubernetes": {
              "serviceAccountRef": {
                "name": "cert-manager-acme-dns01-route53"
              }
            },
          },
        }
      }
    }]
  }
}

AZURE_CLOUD = {
  "acme": {
    "server": "https://acme-v02.api.letsencrypt.org/directory",
    "email": os.getenv("EMAIL_CERT"),
    "privateKeySecretRef": {
      "name": "letsencrypt-staging"
    },
    "solvers": [{
      "dns01": {
        "azureDNS": {
          "clientID": os.getenv("SP_ID"),
          "environment": "AzurePublicCloud",
          "clientSecretSecretRef": {
            "name": os.getenv("SECRET_NAME"),
            "key": "SP_SECRET"
          },
          "resourceGroupName": os.getenv("RG_NAME"),
          "subscriptionID": os.getenv("SUBSCRIPTION_ID"),
          "hostedZoneName": os.getenv("HOSTED_ZONE"),
          "tenantID": os.getenv("TENANT_ID"),
        }
      }
    }]
  }
}

LOCAL_SETUP= {"selfSigned": {}}

BASIC_YAML = {
  "apiVersion": "cert-manager.io/v1",
  "kind": "ClusterIssuer",
  "metadata":{
    "name": "ssl-issuer",
    "namespace": os.getenv("NAMESPACE"),
    "annotations":{
      "helm.sh/hook": "post-install, post-upgrade"
    },
    },
  "spec": {}
}
print(f"Using env: {os.getenv("ENVIRONMENT")}")

match os.getenv("ENVIRONMENT"):
  case "azure":
    BASIC_YAML["spec"] = AZURE_CLOUD
  case "aws":
    BASIC_YAML["spec"] = AWS_CLOUD
  case _:
    BASIC_YAML["spec"] = LOCAL_SETUP

with open("issuer.yaml", 'w') as file:
  yaml.dump(BASIC_YAML, file, default_flow_style=False)
