#!/bin/sh

cd opt/keycloak/bin/

# --optimized is required: without it this command re-runs the build and silently discards the baked
# build options, so the server then starts with features=<unset>.
bootstrap=$(./kc.sh bootstrap-admin user --optimized \
    --username:env KC_BOOTSTRAP_ADMIN_USERNAME \
    --password:env KC_BOOTSTRAP_ADMIN_PASSWORD 2>&1)
echo "$bootstrap"

# An --optimized server ignores build-time options given at runtime, warning rather than failing. A
# Keycloak upgrade that reclassifies an option as build-time would therefore start healthy with that
# option quietly unset. Fail instead: everything build-time belongs in kc.sh build in the Dockerfile.
if echo "$bootstrap" | grep -q "differ from what is persisted"; then
    echo "FATAL: build-time options were passed at runtime and will be ignored (see above)." >&2
    echo "Bake them into 'kc.sh build' in build/keycloak/Dockerfile, or drop them from the env." >&2
    exit 1
fi

echo "Running with $@"
exec ./kc.sh "$@"
