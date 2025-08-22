#!/bin/sh

set -e

if [ -n "$KERBEROS" ]; then
    echo "Requesting Kerberos ticket"
    if [ -e "/etc/krb5.conf" ]; then
        export KRB5_CONFIG="/etc/krb5.conf"
        echo "$PASSWORD" | kinit "${USER}"
    else
        echo "krb5 configuration file missing"
        exit 1
    fi
fi

python3 -m connector
