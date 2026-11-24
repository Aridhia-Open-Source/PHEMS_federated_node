"""
Health checks, one per resource kind, for the healthcheck routes. A failed check is reported in the body,
never raised, and nothing returned includes a secret's value.
"""
