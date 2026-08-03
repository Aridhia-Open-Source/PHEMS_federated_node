FROM quay.io/keycloak/keycloak:26.4

ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

COPY --chmod=755 entrypoint.sh /opt/keycloak/bin/

COPY kc-features.txt /opt/keycloak/kc-features.txt

# Every build-time option must be baked here. Anything left out is unset for an --optimized server,
# regardless of what the runtime environment provides. db and health-enabled are build-time; the
# KC_DB_URL_* / credentials are not.
RUN /opt/keycloak/bin/kc.sh build \
    --features="$(tr -d '\n' < /opt/keycloak/kc-features.txt)" \
    --db=postgres \
    --health-enabled=true

# Re-enable SHA1 to be able to talk to azure postgres service
USER root
RUN sed -i 's/SHA1, //' /etc/crypto-policies/back-ends/java.config \
    && echo "${USERNAME}:x:${USER_GID}" >> /etc/group \
    && echo "${USERNAME}:x:${USER_UID}:${USER_GID}:${USERNAME}} user:/opt/keycloak:/sbin/nologin" >> /etc/passwd \
    && chown -cR "${USERNAME}:${USERNAME}" /opt/keycloak

USER ${USER_UID}
ENTRYPOINT [ "/opt/keycloak/bin/entrypoint.sh" ]
