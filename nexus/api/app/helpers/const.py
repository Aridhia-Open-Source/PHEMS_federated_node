import os

# The Keycloak groups or realm roles whose records only their members may change (ADR 0036), comma separated
OWNER_GROUPS = [g.strip() for g in os.getenv("OWNER_GROUPS", "service-account").split(",") if g.strip()]

