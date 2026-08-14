FROM quay.io/keycloak/keycloak:26.4

ARG APP_USER=fednode
ARG USER_UID=1001
ARG USER_GID=1001
COPY --chmod=755 entrypoint.sh /opt/keycloak/bin/

RUN /opt/keycloak/bin/kc.sh build --features="admin-fine-grained-authz:v1,token-exchange"

# Re-enable SHA1 to be able to talk to azure postgres service
USER root
RUN sed -i 's/SHA1, //' /etc/crypto-policies/back-ends/java.config \
    && echo "${APP_USER}:x:${USER_GID}" >> /etc/group \
    && echo "${APP_USER}:x:${USER_UID}:${USER_GID}:${APP_USER}} user:/opt/keycloak:/sbin/nologin" >> /etc/passwd \
    && chown -cR "${APP_USER}:${APP_USER}" /opt/keycloak

USER ${USER_UID}
ENTRYPOINT [ "/opt/keycloak/bin/entrypoint.sh" ]
