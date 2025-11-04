#!/bin/sh

cd opt/keycloak/bin/
./kc.sh bootstrap-admin user --username:env KC_BOOTSTRAP_ADMIN_USERNAME --password:env KC_BOOTSTRAP_ADMIN_PASSWORD
./kc.sh "$@"
