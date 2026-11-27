"""Test target for the security scanners (ADR 0044): deliberately loose settings so the
Semgrep rules for Pulumi have something to find. Never deployed. The Pulumi stack's real
cluster and storage code (project/plans/azure-network-and-aks.md) replaces this file."""
import pulumi_azure_native as azure

group = azure.resources.ResourceGroup("scan-test")

# test target: public blob access, plain HTTP, old TLS
storage = azure.storage.StorageAccount(
    "scantest",
    resource_group_name=group.name,
    kind="StorageV2",
    sku=azure.storage.SkuArgs(name="Standard_LRS"),
    allow_blob_public_access=True,
    enable_https_traffic_only=False,
    minimum_tls_version="TLS1_0",
)

# test target: no network policy, no RBAC, no authorized API server ranges
aks = azure.containerservice.ManagedCluster(
    "scantest",
    resource_group_name=group.name,
    dns_prefix="scantest",
    enable_rbac=False,
    identity=azure.containerservice.ManagedClusterIdentityArgs(type="SystemAssigned"),
    agent_pool_profiles=[
        azure.containerservice.ManagedClusterAgentPoolProfileArgs(
            name="system", count=1, vm_size="Standard_B2s", mode="System"
        )
    ],
    network_profile=azure.containerservice.ContainerServiceNetworkProfileArgs(network_plugin="kubenet"),
)
