
FROM alpine:3.19.0

WORKDIR /jars
ENV INFINISPAN_REPO="https://repo1.maven.org/maven2/org/infinispan"
ENV INFINISPAN_VERSION="14.0.27"
RUN apk update && apk add curl && \
    wget "${INFINISPAN_REPO}/infinispan-cachestore-jdbc/${INFINISPAN_VERSION}.Final/infinispan-cachestore-jdbc-${INFINISPAN_VERSION}.Final.jar" && \
    wget "${INFINISPAN_REPO}/infinispan-cachestore-jdbc-common-jakarta/${INFINISPAN_VERSION}.Final/infinispan-cachestore-jdbc-common-jakarta-${INFINISPAN_VERSION}.Final.jar" && \
    curl https://cacerts.digicert.com/DigiCertGlobalRootG2.crt.pem -o /DigiCertGlobalRootCA.crt.pem

FROM quay.io/keycloak/keycloak:24.0.2

ARG USERNAME=fednode
ARG USER_UID=1001
ARG USER_GID=1001

COPY cache-ispn.xml /opt/keycloak/conf/
COPY --from=0 /jars /opt/keycloak/providers
COPY --from=0 /DigiCertGlobalRootCA.crt.pem /opt/keycloak/.postgres/root.crt.pem
RUN /opt/keycloak/bin/kc.sh build --cache=ispn --cache-config-file=cache-ispn.xml

# Re-enable SHA1 to be able to talk to azure postgres service
USER root
RUN sed -i 's/SHA1, //' /etc/crypto-policies/back-ends/java.config \
    && echo "${USERNAME}:x:${USER_GID}" >> /etc/group \
    && echo "${USERNAME}:x:${USER_UID}:${USER_GID}:${USERNAME}} user:/opt/keycloak:/sbin/nologin" >> /etc/passwd \
    && chown -cR "${USERNAME}:${USERNAME}" /opt/keycloak

USER ${USER_UID}
