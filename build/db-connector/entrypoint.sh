#!/bin/sh

set -e

echo "Using Kerberos? ${KERBEROS:-No}"

if [ -n "$KERBEROS" ]; then
    echo "Requesting Kerberos ticket"
    if [ -e "/etc/krb5.conf" ]; then
        export KRB5_CONFIG="/etc/krb5.conf"
        kinit -kft /etc/principal.keytab "${PGUSER}"
        klist -kt /etc/principal.keytab
    else
        echo "krb5 configuration file missing"
        exit 1
    fi
fi

python3 -m connector
