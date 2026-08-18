"""
Give the `global` client secret a rotation grace period.

Without this, regenerating the client secret is an immediate cutover: the old secret stops working
the instant the new one is issued, so every pod still holding the old value fails until it picks up
the new one. With the policy in place Keycloak keeps the previous secret valid for
`rotatedExpirationPeriod`, which is what makes the rotation CronJob a no-downtime operation.

The grace period is set far longer than the ~2 minutes Kubernetes needs to sync a mounted Secret
into running pods, so there is generous margin.
"""
from common import set_client_secret_rotation_policy

VERSION = 2
DESCRIPTION = "client secret rotation policy for the global client"


def migrate(admin_token: str):
    set_client_secret_rotation_policy(admin_token)
