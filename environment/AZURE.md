# Environment Creation - Azure Cloud

## Introduction

This page briefly shows how to create the envrionment needed by the Federated Node server on Azure.

## Requirements
The below resources are required in order to deploy Federated Node remotely. The below shows the way to deploy them on Azure Cloud. It is also possible to setup the equivalant environment with other cloud providers or on-premises environment.
1. Kuberenetes Cluster
2. PostgreSQL Server
3. Blob Storage

## Step-by-step reference - Azure

### Set the variables

```
LOCATION=<Azure region, e.g. uksouth>
TID=<Tenant ID, e.g. an identifiable name>
SUB=<Azure subscription ID>
AUTHORISED_IP_RANGES=<list of whitelisted IP to access the K8S cluster API server>
```
e.g. Use the current network WLAN IP `AUTHORISED_IP_RANGES="$(curl ipinfo.io/ip)/32"`

### Switch to the target subscription
```
az account set -s $SUB
```

### Create the resource group
```
RG="fn-${TID}"
az group create --location $LOCATION --name $RG --tags "product=FederatedNode"
```

### Create the virtual network
```
az network vnet create --name "vnet-${RG}" \
                       --resource-group "$RG" \
                       --address-prefix 10.3.0.0/16 \
                       --subnet-name federatedNode \
                       --subnet-prefixes 10.3.0.0/24
```

### Create a subnet for Federated Node in the virtual network
```
az network vnet subnet create --name federatedNode \
                              --resource-group "$RG" \
                              --vnet-name "vnet-${RG}" \
                              --address-prefixes 10.3.0.0/24
```

### Create another subnet for the kubernetes cluster in the virtual network
```
az network vnet subnet create --name kubernetes \
                              --resource-group "$RG" \
                              --vnet-name "vnet-${RG}" \
                              --address-prefixes 10.3.2.0/23
```

### Get the subnet IDs for later creation
```
K8S_SUBNET_ID=$(az network vnet subnet show --name kubernetes --resource-group "$RG" --vnet-name "vnet-${RG}" --query id -o tsv)
FN_SUBNET_ID=$(az network vnet subnet show --name federatedNode --resource-group "$RG" --vnet-name "vnet-${RG}" --query id -o tsv)
```

### Create the AKS (Kubernetes Cluster)
```
az aks create --name "${RG}-k8s" \
              --resource-group "$RG" \
              --location "$LOCATION" \
              --api-server-authorized-ip-ranges "$AUTHORISED_IP_RANGES" \
              --enable-managed-identity \
              --load-balancer-sku standard \
              --vnet-subnet-id "$K8S_SUBNET_ID" \
              --network-plugin azure \
              --nodepool-name agentpool \
              --enable-cluster-autoscaler \
              --min-count 1 \
              --max-count 4 \
              --node-vm-size Standard_DS3_v2
```

### Get the kubernetes context
```
az aks get-credentials -n "${RG}-k8s" -g $RG
```

### Create private DNS zone for PostgreSQL server
```
az network private-dns zone create -g "${RG}" -n "${RG}.private.postgres.database.azure.com"
```

### Get the private DNS zone ID for PostgresSQL creation
```
PRIVATE_DNS_ZONE_ID=$(az network private-dns zone show -n "${RG}.private.postgres.database.azure.com" -g "$RG" --query id -o tsv)
```

### Create Azure PostgreSQL flexible server
Remember to take a note with the login creds from the output
```
az postgres flexible-server create --name "${RG}-postgres" \
                                   --resource-group "$RG" \
                                   --subnet "$FN_SUBNET_ID" \
                                   --private-dns-zone "$PRIVATE_DNS_ZONE_ID" \
                                   --tier Burstable \
                                   --sku-name Standard_B2s \
                                   --storage-size 32
```

### Create a database within PostgreSQL
```
az postgres flexible-server db create --resource-group "$RG" \
                                      --server-name "${RG}-postgres" \
                                      --database-name "federatedNode"
```

### Create the storage account for blob storage
```
SA_NAME=$(echo "${RG}$(uuidgen)" | sed 's/[-]//g' | head -c 15)
az storage account create --name "$SA_NAME" \
                          --resource-group "$RG" \
                          --access-tier Hot \
                          --public-network-access Disabled
```

### Enable the service endpoint for storage account in the k8s subnet
```
az network vnet subnet update -g "$RG" -n "kubernetes" --vnet-name "vnet-${RG}" --service-endpoints Microsoft.Storage
```

### Allow the access from the subnet for the Kubernetes cluster to the storage account
```
az storage account network-rule add --resource-group "$RG" --account-name "$SA_NAME" --subnet "$K8S_SUBNET_ID"
```

### Open public access and restrict it to the subnet just added
```
az storage account update --name $SA_NAME --resource-group $RG --public-network-access Enabled
az storage account update --name $SA_NAME --resource-group $RG --default-action Deny
```

### Create the container (blob storage)
```
az storage container create --name federatednode \
                            --account-name "$SA_NAME"
```

## Storage Backup (Optional)

### Create a separated resource group for the backups
```
az group create \
  --location "${LOCATION}" \
  --name "bac-${RG}" \
  --tags "product=FederatedNode"
```
### Create a recovery service vault
```
az backup vault create \
  --resource-group "bac-${RG}" \
  --name "bac-${RG}-recovery" \
  --location "${LOCATION}" \
  --tags "product=FederatedNode"
```

### Create a backup policy for the file share from the storage account
```
az backup policy create \
  --resource-group "bac-${RG}" \
  --vault-name "bac-${RG}-recovery" \
  --name "federatednode-files-policy" \
  --backup-management-type AzureStorage \
  --workload-type AzureFileShare \
  --policy \
  '{
    "properties": {
      "backupManagementType": "AzureStorage",
      "protectedItemsCount": 2,
      "resourceGuardOperationRequests": null,
      "retentionPolicy": {
        "dailySchedule": {
          "retentionDuration": {
            "count": 14,
            "durationType": "Days"
          },
          "retentionTimes": [
            "2026-02-11T01:00:00"
          ]
        },
        "monthlySchedule": null,
        "retentionPolicyType": "LongTermRetentionPolicy",
        "weeklySchedule": null,
        "yearlySchedule": null
      },
      "schedulePolicy": {
        "hourlySchedule": null,
        "schedulePolicyType": "SimpleSchedulePolicy",
        "scheduleRunDays": null,
        "scheduleRunFrequency": "Daily",
        "scheduleRunTimes": [
          "2026-02-11T01:00:00"
        ],
        "scheduleWeeklyFrequency": 0
      },
      "timeZone": "GMT Standard Time",
      "vaultRetentionPolicy": null,
      "workLoadType": "AzureFileShare"
    }
  }'
```

### Associate the file share to the backup policy
```
az backup protection enable-for-azurefileshare \
  --resource-group "bac-${RG}" \
  --vault-name "bac-${RG}-recovery" \
  --storage-account "${SA_NAME}" \
  --azure-file-share "files" \
  --policy-name "federatednode-files-policy"
```